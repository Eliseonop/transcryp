"""
Interfaz grafica del transcriptor local (faster-whisper).

- Arrastra uno o VARIOS videos/audios (o una carpeta entera) a la ventana, o
  pulsa "Elegir archivos". Todo entra en una COLA y se transcribe uno tras otro.
- Detecta si es video o audio y su duracion.
- Si es CORTO: muestra el texto para copiar/pegar (clic en la fila para verlo).
- Si es LARGO: guarda los archivos y ofrece vista previa + abrir la carpeta.
- Con "Guardar organizado por curso" cada archivo de la cola se guarda como
  .txt en la carpeta del curso elegido.
- Puedes elegir el idioma del audio (o dejar que lo detecte solo).
- "🌐 Traductor en vivo" abre una herramienta que escucha lo que suena en el PC
  (o un microfono) en ingles y muestra la transcripcion y, al lado, la
  traduccion al espanol (ver app/gui_traductor.py).

Se ejecuta desde la raiz del proyecto con:  python main.py
"""
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

# --- permitir importar el modulo transcribir.py de la carpeta padre ---
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

import transcribir as T  # noqa: E402
from cursos import (limpiar_nombre, transcripciones_existentes,  # noqa: E402
                    ruta_txt_libre)
from app import config, setup_modelos  # noqa: E402

# Drag & drop (opcional): si no esta instalado, la app sigue funcionando con el boton.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
except Exception:
    _DND = False

# ----------------------------- configuracion -----------------------------

VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v",
         ".mpg", ".mpeg", ".ts"}
AUDIO = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma",
         ".aiff", ".alac"}

# Umbral corto/largo (en segundos). <= 8 min se considera "corto".
UMBRAL_CORTO = 8 * 60

# Carpeta donde se guardan las transcripciones largas.
CARPETA_SALIDA = Path.home() / "Desktop" / "Transcripciones"
if not CARPETA_SALIDA.parent.is_dir():          # por si el Escritorio esta en otra ruta
    CARPETA_SALIDA = Path.home() / "Transcripciones"

# Idiomas ofrecidos: etiqueta -> codigo (None = detectar automatico)
IDIOMAS = [
    ("Detectar automatico", None),
    ("Espanol", "es"),
    ("Ingles", "en"),
    ("Portugues", "pt"),
    ("Frances", "fr"),
    ("Italiano", "it"),
    ("Aleman", "de"),
    ("Chino", "zh"),
    ("Japones", "ja"),
]

# Modelo -> descripcion para el selector de calidad/velocidad
MODELOS = [
    ("Maxima calidad (large-v3)", "large-v3"),
    ("Equilibrado (medium)", "medium"),
    ("Rapido (small)", "small"),
    ("Muy rapido (base)", "base"),
]

# Estados de cada archivo de la cola
PENDIENTE, TRABAJANDO, LISTO, ERROR = "pendiente", "trabajando", "listo", "error"


# ----------------------------- utilidades -----------------------------

def tipo_de(ruta: Path) -> str:
    ext = ruta.suffix.lower()
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    return "desconocido"


def orden_natural(texto: str):
    """Clave de orden 'humano': 'Clase 2' va antes que 'Clase 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", texto)]


def expandir_rutas(rutas) -> tuple[list[Path], int]:
    """Archivos a encolar a partir de lo soltado/elegido.

    Las carpetas se recorren (con subcarpetas) y de ellas solo se toman videos y
    audios. Todo va en orden natural. Devuelve (archivos, n_formato_raro), donde
    n_formato_raro cuenta los archivos sueltos con extension no reconocida (se
    encolan igual, por si acaso)."""
    archivos, raros = [], 0
    for r in sorted((Path(r) for r in rutas), key=lambda p: orden_natural(p.name)):
        if r.is_dir():
            medios = [f for f in r.rglob("*")
                      if f.is_file() and tipo_de(f) != "desconocido"]
            medios.sort(key=lambda f: orden_natural(str(f.relative_to(r))))
            archivos.extend(medios)
        elif r.is_file():
            if tipo_de(r) == "desconocido":
                raros += 1
            archivos.append(r)
    return archivos, raros


def duracion_segundos(ruta: Path) -> float | None:
    """Duracion del medio usando ffprobe (viene con ffmpeg). None si falla."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(ruta)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def dur_bonita(seg: float | None) -> str:
    if not seg:
        return "?"
    s = int(round(seg))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def texto_de_segmentos(segmentos) -> str:
    """Convierte segmentos en texto plano legible (con hablantes si los hay)."""
    lineas, actual = [], object()
    for seg in segmentos:
        hab = seg.get("speaker")
        if hab and hab != actual:
            if actual is not object():
                lineas.append("")
            lineas.append(f"{hab}:")
            actual = hab
        lineas.append(seg["text"].strip())
    return "\n".join(lineas).strip()


class _Cancelado(Exception):
    """El usuario pulso 'Detener' mientras se transcribia."""


# ----------------------------- aplicacion -----------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.modelo = None
        self.modelo_nombre = None
        self.modelo_device = "cpu"
        self.diarizador = None
        self.trabajando = False      # hay algo en marcha (cola o preparar modelos)
        self.ultimo_dir = None
        self.cursos = config.cargar_cursos()
        self.ventana_trad = None     # herramienta "Traductor en vivo" (si esta abierta)

        # --- cola ---
        self.cola = {}               # iid de la tabla -> datos del archivo
        self.actual = None           # iid que se esta transcribiendo
        self.cola_activa = False
        self.detener = False
        self.mostrado = None         # iid cuyo resultado se ve en el cuadro de texto
        self._motivo_parada = None
        self._tanda_n = self._tanda_total = 0
        self._tanda_ok = self._tanda_err = 0

        root.title("Transcriptor  ·  arrastra tus videos o audios")
        root.geometry("820x780")
        root.minsize(700, 640)
        root.protocol("WM_DELETE_WINDOW", self._al_cerrar)
        self._construir()
        self._actualizar_botones()

    # ---------- construccion de la interfaz ----------
    def _construir(self):
        cont = ttk.Frame(self.root, padding=16)
        cont.pack(fill="both", expand=True)

        # --- zona de arrastre ---
        self.zona = tk.Label(
            cont,
            text=("⬇  Arrastra aqui uno o VARIOS videos/audios (o una carpeta)\n"
                  "Se ponen en cola y se transcriben uno tras otro  ·  "
                  "(o pulsa aqui para elegirlos)"),
            font=("Segoe UI", 12), justify="center",
            relief="ridge", bd=2, height=4,
            bg="#f4f6fb", fg="#33415c", cursor="hand2",
        )
        self.zona.pack(fill="x", pady=(0, 12))
        self.zona.bind("<Button-1>", lambda e: self.elegir_archivo())

        # --- fila de opciones ---
        ops = ttk.Frame(cont)
        ops.pack(fill="x", pady=(0, 10))

        ttk.Label(ops, text="Idioma:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.cbo_idioma = ttk.Combobox(
            ops, state="readonly", width=22,
            values=[e for e, _ in IDIOMAS])
        self.cbo_idioma.current(0)
        self.cbo_idioma.grid(row=0, column=1, sticky="w", padx=(0, 18))

        ttk.Label(ops, text="Calidad:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.cbo_modelo = ttk.Combobox(
            ops, state="readonly", width=26,
            values=[e for e, _ in MODELOS])
        self.cbo_modelo.current(0)
        self.cbo_modelo.grid(row=0, column=3, sticky="w")

        self.var_diar = tk.BooleanVar(value=False)
        ttk.Checkbutton(ops, text="Separar quien habla",
                        variable=self.var_diar).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(8, 0))

        # --- guardar organizado por curso ---
        cur = ttk.Frame(cont)
        cur.pack(fill="x", pady=(0, 10))

        self.var_curso = tk.BooleanVar(value=False)
        ttk.Checkbutton(cur, text="Guardar organizado por curso",
                        variable=self.var_curso,
                        command=self._toggle_curso).grid(
            row=0, column=0, columnspan=4, sticky="w")

        # carpeta donde se guardan los cursos (configurable)
        ttk.Label(cur, text="Carpeta:").grid(
            row=1, column=0, sticky="w", padx=(20, 6), pady=(6, 0))
        self.lbl_carpeta = ttk.Label(cur, text="", foreground="#33415c")
        self.lbl_carpeta.grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(cur, text="Cambiar…", width=10,
                   command=self._cambiar_carpeta).grid(
            row=1, column=3, sticky="e", pady=(6, 0))

        ttk.Label(cur, text="Curso:").grid(
            row=2, column=0, sticky="w", padx=(20, 6), pady=(6, 0))
        self.cbo_curso = ttk.Combobox(
            cur, state="disabled", width=34,
            values=[c["nombre"] for c in self.cursos])
        if self.cursos:
            self.cbo_curso.current(0)
        self.cbo_curso.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0))
        self.cbo_curso.bind("<<ComboboxSelected>>", lambda e: self._mostrar_curso())
        ttk.Button(cur, text="➕ Curso", width=10,
                   command=self._anadir_curso).grid(
            row=2, column=3, sticky="e", pady=(6, 0))

        self.lbl_curso = ttk.Label(cur, text="", foreground="#5a6472")
        self.lbl_curso.grid(row=3, column=0, columnspan=4, sticky="w",
                            padx=(20, 0), pady=(4, 0))
        self._refrescar_carpeta()

        fila_btns = ttk.Frame(cont)
        fila_btns.pack(fill="x")
        ttk.Button(fila_btns, text="📂  Elegir archivos…",
                   command=self.elegir_archivo).pack(side="left")
        ttk.Button(fila_btns, text="🗂  Agregar carpeta…",
                   command=self.elegir_carpeta).pack(side="left", padx=(8, 0))
        self.btn_prep = ttk.Button(
            fila_btns, text="🔧  Verificar / Preparar",
            command=self.preparar_modelos)
        self.btn_prep.pack(side="left", padx=(8, 0))
        ttk.Button(fila_btns, text="🌐  Traductor en vivo (EN→ES)",
                   command=self.abrir_traductor).pack(side="right")

        # --- cola de archivos ---
        self.lbl_cola = ttk.Label(cont, text="Cola:", font=("Segoe UI", 10, "bold"))
        self.lbl_cola.pack(anchor="w", pady=(12, 2))

        marco_cola = ttk.Frame(cont)
        marco_cola.pack(fill="x")
        self.tabla = ttk.Treeview(
            marco_cola, columns=("archivo", "dur", "destino", "estado"),
            show="headings", height=6, selectmode="extended")
        for col, titulo, ancho, estira in (
                ("archivo", "Archivo", 300, True),
                ("dur", "Duracion", 90, False),
                ("destino", "Destino", 180, False),
                ("estado", "Estado", 120, False)):
            self.tabla.heading(col, text=titulo, anchor="w")
            self.tabla.column(col, width=ancho, stretch=estira, anchor="w")
        self.tabla.tag_configure(TRABAJANDO, foreground="#1a56db")
        self.tabla.tag_configure(LISTO, foreground="#1e7b34")
        self.tabla.tag_configure(ERROR, foreground="#b3261e")
        scroll_cola = ttk.Scrollbar(marco_cola, command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll_cola.set)
        self.tabla.pack(side="left", fill="x", expand=True)
        scroll_cola.pack(side="right", fill="y")
        self.tabla.bind("<<TreeviewSelect>>", lambda e: self._al_seleccionar())
        self.tabla.bind("<Delete>", lambda e: self.quitar_seleccion())

        fila_cola = ttk.Frame(cont)
        fila_cola.pack(fill="x", pady=(6, 0))
        self.btn_go = ttk.Button(fila_cola, text="▶  Transcribir",
                                 command=self.transcribir, state="disabled")
        self.btn_go.pack(side="left")
        self.btn_stop = ttk.Button(fila_cola, text="⏹  Detener",
                                   command=self.detener_cola, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_limpiar = ttk.Button(fila_cola, text="🧹  Limpiar terminados",
                                      command=self.limpiar_terminados,
                                      state="disabled")
        self.btn_limpiar.pack(side="right")
        self.btn_quitar = ttk.Button(fila_cola, text="✖  Quitar",
                                     command=self.quitar_seleccion, state="disabled")
        self.btn_quitar.pack(side="right", padx=(0, 8))

        if _DND:
            for w in (self.zona, self.tabla):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._al_soltar)

        # --- estado / progreso ---
        self.lbl_info = ttk.Label(cont, text="Cola vacia.", foreground="#5a6472")
        self.lbl_info.pack(fill="x", pady=(12, 4))

        self.barra = ttk.Progressbar(cont, mode="determinate", maximum=100)
        self.barra.pack(fill="x")

        # --- resultado ---
        self.lbl_res = ttk.Label(cont, text="Resultado:", font=("Segoe UI", 10, "bold"))
        self.lbl_res.pack(anchor="w", pady=(10, 2))

        marco_txt = ttk.Frame(cont)
        marco_txt.pack(fill="both", expand=True)
        self.txt = tk.Text(marco_txt, wrap="word", font=("Consolas", 10),
                           height=8, bg="#ffffff")
        scroll = ttk.Scrollbar(marco_txt, command=self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        self.txt.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # --- botones de accion sobre el resultado ---
        # (se empaquetan antes que el texto para que nunca queden cortados)
        acc = ttk.Frame(cont)
        acc.pack(side="bottom", fill="x", pady=(8, 0), before=marco_txt)
        self.btn_copiar = ttk.Button(acc, text="📋  Copiar texto",
                                     command=self.copiar, state="disabled")
        self.btn_copiar.pack(side="left")
        self.btn_guardar = ttk.Button(acc, text="💾  Guardar como…",
                                      command=self.guardar_como, state="disabled")
        self.btn_guardar.pack(side="left", padx=(8, 0))
        self.btn_carpeta = ttk.Button(acc, text="📁  Abrir carpeta",
                                      command=self.abrir_carpeta, state="disabled")
        self.btn_carpeta.pack(side="left", padx=(8, 0))

        if not _DND:
            self.lbl_info.config(
                text="Sugerencia: instala 'tkinterdnd2' para arrastrar archivos. "
                     "Mientras, usa el boton 'Elegir archivos'.")

    # ---------- agregar archivos a la cola ----------
    def _al_soltar(self, event):
        # splitlist entiende las rutas con espacios ({C:/mi carpeta/a.mp4} ...)
        self.agregar(self.root.tk.splitlist(event.data))

    def elegir_archivo(self):
        exts = " ".join("*" + e for e in sorted(VIDEO | AUDIO))
        rutas = filedialog.askopenfilenames(
            title="Elige uno o varios videos/audios",
            filetypes=[("Video/Audio", exts), ("Todos", "*.*")])
        if rutas:
            self.agregar(rutas)

    def elegir_carpeta(self):
        ruta = filedialog.askdirectory(
            title="Elige una carpeta con videos o audios")
        if ruta:
            self.agregar([ruta])

    def agregar(self, rutas):
        archivos, raros = expandir_rutas(rutas)
        ya = {it["ruta"] for it in self.cola.values()
              if it["estado"] in (PENDIENTE, TRABAJANDO)}
        # con la cola en marcha, lo nuevo usa las opciones de este momento
        opc = self._opciones_actuales(avisar=False) if self.cola_activa else None
        nuevos = []
        for ruta in archivos:
            if ruta in ya:                       # ya esta esperando: no duplicar
                continue
            ya.add(ruta)
            iid = self.tabla.insert("", "end")
            self.cola[iid] = {
                "ruta": ruta, "dur": None, "dur_txt": "…", "estado": PENDIENTE,
                "opciones": opc, "texto": "", "error": None,
                "carpeta": None, "titulo": "", "resumen": "", "guardado": False,
            }
            self._pintar(iid)
            nuevos.append((iid, ruta))

        if self.cola_activa:
            self._tanda_total += len(nuevos)
        if nuevos:
            msg = f"Se agrego(aron) {len(nuevos)} archivo(s) a la cola."
            if raros:
                msg += f"  ({raros} con formato no reconocido: se intentara igualmente)"
            if not self.cola_activa:
                msg += "  Pulsa 'Transcribir' cuando quieras."
                self.lbl_info.config(text=msg)
            self.tabla.see(nuevos[-1][0])
            # duraciones en segundo plano (ffprobe puede tardar un poco)
            threading.Thread(target=self._analizar_lote, args=(nuevos,),
                             daemon=True).start()
        elif not self.cola_activa:
            self.lbl_info.config(
                text="No se encontraron videos/audios nuevos para agregar.")
        self._actualizar_botones()

    def _analizar_lote(self, pares):
        for iid, ruta in pares:
            dur = duracion_segundos(ruta)
            self.root.after(0, lambda i=iid, d=dur: self._dur_lista(i, d))

    def _dur_lista(self, iid, dur):
        it = self.cola.get(iid)
        if it is None or not self.tabla.exists(iid):
            return
        it["dur"], it["dur_txt"] = dur, dur_bonita(dur)
        self.tabla.set(iid, "dur", it["dur_txt"])
        self._actualizar_botones()

    # ---------- tabla de la cola ----------
    def _destino_txt(self, opc) -> str:
        curso = opc["curso"] if opc is not None else self._curso_elegido()
        return curso["nombre"] if curso else "Sin curso"

    def _pintar(self, iid, estado_txt=None):
        """Redibuja la fila de un archivo de la cola."""
        it = self.cola[iid]
        if estado_txt is None:
            estado_txt = {
                PENDIENTE: "En cola",
                TRABAJANDO: "⏳ …",
                LISTO: "✓ Guardado" if it["guardado"] else "✓ Listo (copiar)",
                ERROR: "✗ Error",
            }[it["estado"]]
        self.tabla.item(iid, tags=(it["estado"],), values=(
            it["ruta"].name, it["dur_txt"], self._destino_txt(it["opciones"]),
            estado_txt))

    def _refrescar_destinos(self):
        """Los pendientes sin opciones fijadas muestran el curso elegido ahora."""
        for iid, it in self.cola.items():
            if it["estado"] == PENDIENTE and it["opciones"] is None:
                self._pintar(iid)

    def _pendientes(self) -> list:
        return [i for i in self.tabla.get_children()
                if self.cola[i]["estado"] == PENDIENTE]

    def _al_seleccionar(self):
        sel = self.tabla.selection()
        if len(sel) == 1:
            self._mostrar_item(sel[0])
        self._actualizar_botones()

    def quitar_seleccion(self):
        for iid in self.tabla.selection():
            if iid == self.actual:               # el que se transcribe no se quita
                continue
            if self.cola_activa and self.cola[iid]["estado"] == PENDIENTE:
                self._tanda_total -= 1
            self._borrar_fila(iid)
        self._actualizar_botones()

    def limpiar_terminados(self):
        for iid in list(self.cola):
            if self.cola[iid]["estado"] in (LISTO, ERROR):
                self._borrar_fila(iid)
        self._actualizar_botones()

    def _borrar_fila(self, iid):
        self.tabla.delete(iid)
        del self.cola[iid]
        if self.mostrado == iid:
            self._resetear_resultado()

    def _actualizar_botones(self):
        pend = self._pendientes()
        n = len(pend)
        self.btn_go.config(
            text=f"▶  Transcribir ({n})" if n > 1 else "▶  Transcribir",
            state="normal" if n and not self.trabajando else "disabled")
        self.btn_stop.config(
            state="normal" if self.cola_activa and not self.detener else "disabled")
        quitables = [i for i in self.tabla.selection() if i != self.actual]
        self.btn_quitar.config(state="normal" if quitables else "disabled")
        terminados = [it for it in self.cola.values() if it["estado"] in (LISTO, ERROR)]
        self.btn_limpiar.config(state="normal" if terminados else "disabled")
        self.btn_prep.config(state="disabled" if self.trabajando else "normal")

        # resumen sobre la tabla
        partes = []
        if n:
            seg = sum(self.cola[i]["dur"] or 0 for i in pend)
            partes.append(f"{n} en cola" + (f" ({dur_bonita(seg)})" if seg else ""))
        if self.actual:
            partes.append("1 transcribiendose")
        listos = sum(1 for it in terminados if it["estado"] == LISTO)
        errores = len(terminados) - listos
        if listos:
            partes.append(f"{listos} listo(s)")
        if errores:
            partes.append(f"{errores} con error")
        self.lbl_cola.config(text="Cola:  " + ("  ·  ".join(partes) if partes else "vacia"))

    # ---------- opciones de curso ----------
    def _toggle_curso(self):
        on = self.var_curso.get()
        self.cbo_curso.config(state=("readonly" if on and self.cursos else "disabled"))
        if on and not self.cursos:
            self.lbl_curso.config(
                text="Aun no hay cursos. Pulsa '➕ Curso' para anadir el primero.")
        elif on:
            self._mostrar_curso()
        else:
            self.lbl_curso.config(text="")
        self._refrescar_destinos()

    def _refrescar_carpeta(self):
        self.lbl_carpeta.config(text=str(config.carpeta_cursos()))

    def _cambiar_carpeta(self):
        ruta = filedialog.askdirectory(
            title="Elige la carpeta donde guardar los cursos",
            initialdir=str(config.carpeta_cursos().parent))
        if ruta:
            config.guardar_carpeta_cursos(ruta)
            self._refrescar_carpeta()
            if self.var_curso.get():
                self._mostrar_curso()

    def _anadir_curso(self):
        nombre = simpledialog.askstring(
            "Anadir curso", "Nombre del curso:", parent=self.root)
        if not nombre or not nombre.strip():
            return
        codigo = simpledialog.askstring(
            "Anadir curso", "Codigo (opcional):", parent=self.root) or ""
        self.cursos = config.agregar_curso(nombre, codigo)
        nombres = [c["nombre"] for c in self.cursos]
        self.cbo_curso.config(values=nombres)
        if nombres:
            self.cbo_curso.current(nombres.index(nombre.strip())
                                   if nombre.strip() in nombres else len(nombres) - 1)
        if self.var_curso.get():
            self.cbo_curso.config(state="readonly")
            self._mostrar_curso()

    def _curso_dir(self, curso) -> Path:
        return config.carpeta_cursos() / limpiar_nombre(curso["nombre"])

    def _curso_elegido(self):
        """Curso marcado en la interfaz, o None si no se guarda por curso."""
        if not (self.var_curso.get() and self.cursos):
            return None
        idx = self.cbo_curso.current()
        return self.cursos[idx if idx >= 0 else 0]

    def _mostrar_curso(self):
        self._refrescar_destinos()
        if not self.cursos:
            return
        idx = self.cbo_curso.current()
        if idx < 0:
            return
        n = transcripciones_existentes(self._curso_dir(self.cursos[idx]))
        guardadas = (f"{n} transcripcion(es) guardada(s)" if n
                     else "Sin transcripciones aun")
        self.lbl_curso.config(
            text=f"{guardadas}   ·   se guarda el .txt con el nombre del video")

    def _opciones_actuales(self, avisar=True):
        """Opciones elegidas ahora (idioma, calidad, hablantes, curso).
        None si 'por curso' esta marcado pero aun no hay cursos."""
        if self.var_curso.get() and not self.cursos:
            if avisar:
                messagebox.showwarning(
                    "Sin cursos",
                    "Aun no hay cursos. Pulsa '➕ Curso' para anadir uno.")
            return None
        return {
            "idioma": dict(IDIOMAS)[self.cbo_idioma.get()],
            "modelo": dict(MODELOS)[self.cbo_modelo.get()],
            "diar": self.var_diar.get(),
            "curso": self._curso_elegido(),
        }

    # ---------- transcripcion (cola) ----------
    def transcribir(self):
        if self.trabajando:
            return
        pend = self._pendientes()
        if not pend:
            return
        opc = self._opciones_actuales()
        if opc is None:
            return
        # al arrancar, todos los pendientes quedan fijados con estas opciones
        for iid in pend:
            self.cola[iid]["opciones"] = dict(opc)
            self._pintar(iid)
        self.trabajando = self.cola_activa = True
        self.detener = False
        self._motivo_parada = None
        self._tanda_n, self._tanda_total = 0, len(pend)
        self._tanda_ok = self._tanda_err = 0
        self._siguiente()

    def detener_cola(self):
        if not self.cola_activa:
            return
        self.detener = True
        self.lbl_info.config(text="⏹ Deteniendo… (el archivo actual vuelve a la cola)")
        self._actualizar_botones()

    def _siguiente(self):
        """Lanza el siguiente pendiente, o termina la cola."""
        self.actual = None
        if self.detener:
            self._fin_cola(detenida=True)
            return
        pend = self._pendientes()
        if not pend:
            self._fin_cola()
            return
        iid = pend[0]
        it = self.cola[iid]
        if it["opciones"] is None:               # agregado sin opciones validas
            it["opciones"] = self._opciones_actuales()
            if it["opciones"] is None:
                self._fin_cola(detenida=True)
                return
        self.actual = iid
        it["estado"] = TRABAJANDO
        self._tanda_n += 1
        self._pintar(iid)
        self.tabla.see(iid)
        self.barra["value"] = 0
        self._actualizar_botones()
        threading.Thread(target=self._trabajo,
                         args=(iid, it["ruta"], dict(it["opciones"])),
                         daemon=True).start()

    def _progreso(self, iid, texto, pct=None, celda=None):
        """Actualiza (desde el hilo de trabajo) la barra, el estado y la fila."""
        def _():
            it = self.cola.get(iid)
            if it is None or self.actual != iid:
                return
            self.lbl_info.config(
                text=f"[{self._tanda_n}/{self._tanda_total}]  {it['ruta'].name}  ·  {texto}")
            if pct is not None:
                self.barra["value"] = pct
            if celda:
                self._pintar(iid, celda)
        self.root.after(0, _)

    def _trabajo(self, iid, ruta, opc):
        fatal = False      # True si falla la preparacion del modelo (afecta a todos)
        try:
            # 1) cargar modelo (una vez, o si cambio de calidad)
            modelo_nom = opc["modelo"]
            if self.modelo is None or self.modelo_nombre != modelo_nom:
                self._progreso(
                    iid, f"Cargando modelo {modelo_nom} (la 1a vez descarga datos)…",
                    0, "⏳ Cargando modelo")
                fatal = True
                self.modelo, self.modelo_device, _ = T.cargar_modelo(modelo_nom)
                self.modelo_nombre = modelo_nom
                fatal = False

            sd = None
            if opc["diar"]:
                if self.diarizador is None:
                    fatal = True
                    if setup_modelos.faltan_modelos():
                        self._progreso(
                            iid, "Descargando modelos de hablantes (solo la 1a vez)…",
                            0, "⏳ Descargando")
                        setup_modelos.verificar_y_descargar(
                            log=lambda m: self._progreso(iid, m))
                    self._progreso(iid, "Cargando identificador de hablantes…",
                                   0, "⏳ Preparando")
                    self.diarizador = T.cargar_diarizador(0)
                    fatal = False
                sd = self.diarizador

            # 2) transcribir con progreso (por lotes = mucho mas rapido)
            lote = T.tam_lote(self.modelo_device, self.modelo_nombre)
            self._progreso(iid, "Transcribiendo…", 0, "⏳ 0%")
            seg_iter, info = T.abrir_transcripcion(
                self.modelo, ruta, idioma=opc["idioma"], palabras=bool(sd), lote=lote)
            total = getattr(info, "duration", 0) or duracion_segundos(ruta) or 0

            segmentos = []
            t0 = time.time()
            for seg in seg_iter:
                if self.detener:
                    raise _Cancelado()
                segmentos.append({
                    "start": round(seg.start, 3), "end": round(seg.end, 3),
                    "text": seg.text.strip(), "words": None})
                if total:
                    pct = min(100, seg.end / total * 100)
                    self._progreso(iid, f"Transcribiendo…  {pct:4.0f}%", pct,
                                   f"⏳ {pct:.0f}%")

            # 3) diarizacion opcional
            if sd is not None:
                if self.detener:
                    raise _Cancelado()
                self._progreso(iid, "Identificando hablantes…", 100, "⏳ Hablantes")
                diar_segs = T.diarizar(sd, ruta)
                for seg in segmentos:
                    seg["speaker"] = (T.hablante_de(seg["start"], seg["end"], diar_segs)
                                      if diar_segs else None)

            tardo = time.time() - t0
            corto = (total or 0) <= UMBRAL_CORTO
            self.root.after(0, lambda: self._item_listo(iid, segmentos, corto, tardo))
        except _Cancelado:
            self.root.after(0, lambda: self._item_cancelado(iid))
        except Exception as e:
            self.root.after(0, lambda err=e, f=fatal: self._item_error(iid, err, f))
        finally:
            self.root.after(0, self._siguiente)

    def _item_listo(self, iid, segmentos, corto, tardo):
        it = self.cola[iid]
        ruta, curso = it["ruta"], it["opciones"]["curso"]
        it["texto"] = texto_de_segmentos(segmentos)
        # en una tanda de varios, los cortos tambien se guardan (si no, se perderian)
        solo_mostrar = corto and self._tanda_total == 1
        try:
            if curso:
                # una carpeta por curso y dentro solo el .txt: <Curso>\<video>.txt
                curso_dir = self._curso_dir(curso)
                curso_dir.mkdir(parents=True, exist_ok=True)
                destino = ruta_txt_libre(curso_dir, ruta.stem)
                T.escribir_txt(segmentos, destino)
                it["carpeta"], it["guardado"] = curso_dir, True
                it["titulo"] = f"Guardado en el curso ({T.mmss(tardo)})"
                it["resumen"] = f"✓ {curso['nombre']}  ->  {destino}"
            elif solo_mostrar:
                it["titulo"] = f"Resultado (listo para copiar · {T.mmss(tardo)})"
                it["resumen"] = ("✓ Transcripcion corta lista. "
                                 "Copia el texto o guardalo si quieres.")
            else:
                # archivo largo (o tanda): guardar automaticamente txt + srt
                nombre = limpiar_nombre(ruta.stem) or "transcripcion"
                destino_dir = CARPETA_SALIDA / nombre
                destino_dir.mkdir(parents=True, exist_ok=True)
                base = destino_dir / nombre
                T.guardar(segmentos, base, ["txt", "srt"])
                it["carpeta"], it["guardado"] = destino_dir, True
                it["titulo"] = f"Vista previa (guardado · {T.mmss(tardo)})"
                it["resumen"] = f"✓ LISTO. Guardado en:  {base.with_suffix('.txt')}   (+ .srt)"
        except Exception as e:
            self._item_error(iid, f"No se pudo guardar: {e}")
            return
        it["estado"] = LISTO
        if it["carpeta"]:
            self.ultimo_dir = it["carpeta"]
        self._tanda_ok += 1
        self._pintar(iid)
        self.barra["value"] = 100
        self._mostrar_si_libre(iid)
        if curso:
            self._mostrar_curso()

    def _item_error(self, iid, err, fatal=False):
        it = self.cola[iid]
        it["estado"], it["error"] = ERROR, str(err)
        self._tanda_err += 1
        self._pintar(iid)
        if fatal:      # sin modelo no tiene sentido seguir con el resto
            self.detener = True
            self._motivo_parada = f"✗ No se pudo preparar el modelo: {err}"
        self._mostrar_si_libre(iid)

    def _item_cancelado(self, iid):
        it = self.cola[iid]
        it["estado"] = PENDIENTE
        self._pintar(iid)
        self.barra["value"] = 0

    def _fin_cola(self, detenida=False):
        self.trabajando = self.cola_activa = False
        self.actual = None
        # los que quedan en cola tomaran las opciones del proximo 'Transcribir'
        for iid, it in self.cola.items():
            if it["estado"] == PENDIENTE:
                it["opciones"] = None
                self._pintar(iid)
        quedan = len(self._pendientes())
        resumen = f"{self._tanda_ok} listo(s)"
        if self._tanda_err:
            resumen += f", {self._tanda_err} con error"

        it = self.cola.get(self.mostrado)
        if self._motivo_parada:
            texto = self._motivo_parada
        elif detenida:
            texto = (f"⏹ Cola detenida: {resumen}. Quedan {quedan} en cola "
                     "(pulsa 'Transcribir' para seguir).")
        elif self._tanda_total == 1 and it and it["estado"] == LISTO:
            texto = it["resumen"]                 # un solo archivo: mensaje de siempre
        else:
            texto = f"✓ Cola terminada: {resumen}."
        self.lbl_info.config(text=texto)
        if self._tanda_total == 1 and it and it["estado"] == ERROR:
            messagebox.showerror("Error al transcribir", it["error"] or "")
        self.root.bell()
        self._actualizar_botones()

    # ---------- resultado ----------
    def _mostrar_si_libre(self, iid):
        """Muestra el resultado recien terminado, salvo que el usuario este
        mirando otro resultado que eligio en la tabla."""
        sel = self.tabla.selection()
        viendo_otro = (len(sel) == 1 and sel[0] != iid
                       and self.cola.get(sel[0], {}).get("estado") in (LISTO, ERROR))
        if not viendo_otro:
            self._mostrar_item(iid)

    def _mostrar_item(self, iid):
        it = self.cola.get(iid)
        if it is None:
            return
        self.mostrado = iid
        self.txt.delete("1.0", "end")
        nombre = it["ruta"].name
        if it["estado"] == LISTO:
            self.txt.insert("1.0", it["texto"])
            self.lbl_res.config(text=f"{it['titulo']}  ·  {nombre}:")
            self.btn_copiar.config(state="normal")
            self.btn_guardar.config(state="normal")
            self.btn_carpeta.config(state="normal" if it["carpeta"] else "disabled")
            if not self.cola_activa:
                self.lbl_info.config(text=it["resumen"])
        elif it["estado"] == ERROR:
            self.txt.insert("1.0", f"✗ Error:\n{it['error']}")
            self.lbl_res.config(text=f"Error en  {nombre}:")
            for b in (self.btn_copiar, self.btn_guardar, self.btn_carpeta):
                b.config(state="disabled")
        else:
            self.lbl_res.config(text=f"Resultado:  {nombre}  (aun no transcrito)")
            for b in (self.btn_copiar, self.btn_guardar, self.btn_carpeta):
                b.config(state="disabled")

    # ---------- preparar / verificar modelos ----------
    def preparar_modelos(self):
        if self.trabajando:
            return
        self.trabajando = True
        self._actualizar_botones()
        self._resetear_resultado()
        self.lbl_res.config(text="Preparacion de modelos:")
        self._log("Verificando modelos para separar hablantes…\n")
        threading.Thread(target=self._trabajo_preparar, daemon=True).start()

    def _log(self, linea):
        def _():
            self.txt.insert("end", linea if linea.endswith("\n") else linea + "\n")
            self.txt.see("end")
        self.root.after(0, _)

    def _trabajo_preparar(self):
        try:
            ok = setup_modelos.verificar_y_descargar(log=self._log)
            self.root.after(0, lambda: self.lbl_info.config(
                text=("✓ Todo listo. Ya puedes 'Separar quien habla'." if ok
                      else "✗ Faltan modelos. Revisa tu conexion e intenta de nuevo.")))
        except Exception as e:
            self._log(f"✗ Error: {e}")
            self.root.after(0, lambda err=e: self.lbl_info.config(text=f"✗ Error: {err}"))
        finally:
            def _fin():
                self.trabajando = False
                self._actualizar_botones()
            self.root.after(0, _fin)

    # ---------- acciones sobre el resultado ----------
    def copiar(self):
        texto = self.txt.get("1.0", "end").strip()
        if not texto:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(texto)
        self.lbl_info.config(text="📋 Texto copiado al portapapeles.")

    def guardar_como(self):
        texto = self.txt.get("1.0", "end").strip()
        if not texto:
            return
        it = self.cola.get(self.mostrado)
        nombre = (limpiar_nombre(it["ruta"].stem) if it else "") or "transcripcion"
        ruta = filedialog.asksaveasfilename(
            title="Guardar transcripcion",
            defaultextension=".txt", initialfile=f"{nombre}.txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")])
        if ruta:
            Path(ruta).write_text(texto, encoding="utf-8")
            self.ultimo_dir = Path(ruta).parent
            if it:
                it["carpeta"], it["guardado"] = self.ultimo_dir, True
                self._pintar(self.mostrado)
            self.btn_carpeta.config(state="normal")
            self.lbl_info.config(text=f"💾 Guardado en: {ruta}")

    def abrir_carpeta(self):
        it = self.cola.get(self.mostrado)
        carpeta = (it and it["carpeta"]) or self.ultimo_dir or CARPETA_SALIDA
        try:
            os.startfile(str(carpeta))       # Windows
        except AttributeError:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(carpeta)])

    # ---------- herramienta: traductor en vivo ----------
    def abrir_traductor(self):
        if self.ventana_trad is not None and self.ventana_trad.viva():
            self.ventana_trad.traer()
            return
        try:
            from app.gui_traductor import VentanaTraductor
            self.ventana_trad = VentanaTraductor(
                self, extensiones=VIDEO | AUDIO, carpeta_salida=CARPETA_SALIDA, dnd=_DND)
        except Exception as e:
            messagebox.showerror("Traductor en vivo", f"No se pudo abrir el traductor:\n{e}")

    # ---------- varios ----------
    def _resetear_resultado(self):
        self.mostrado = None
        self.txt.delete("1.0", "end")
        self.barra["value"] = 0
        self.lbl_res.config(text="Resultado:")
        for b in (self.btn_copiar, self.btn_guardar, self.btn_carpeta):
            b.config(state="disabled")

    def _al_cerrar(self):
        if self.cola_activa and not messagebox.askyesno(
                "Salir",
                "Hay una cola transcribiendose. Si sales, se detiene.\n"
                "¿Salir igualmente?"):
            return
        trad = self.ventana_trad
        if (not self.cola_activa and trad is not None and trad.ocupada()
                and not messagebox.askyesno(
                    "Salir",
                    "El traductor en vivo esta trabajando. Si sales, se detiene.\n"
                    "¿Salir igualmente?")):
            return
        if trad is not None and trad.viva():
            trad.apagar()
        self.root.destroy()


def lanzar():
    root = TkinterDnD.Tk() if _DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    lanzar()
