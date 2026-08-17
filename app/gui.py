"""
Interfaz grafica del transcriptor local (faster-whisper).

- Arrastra un video o audio a la ventana (o pulsa "Elegir archivo").
- Detecta si es video o audio y su duracion.
- Si es CORTO: transcribe y muestra el texto ahi mismo para copiar/pegar.
- Si es LARGO: transcribe, guarda los archivos y ofrece vista previa + botones
  para guardar/abrir la carpeta.
- Puedes elegir el idioma del audio (o dejar que lo detecte solo).

Se ejecuta desde la raiz del proyecto con:  python main.py
"""
import os
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
from cursos import (limpiar_nombre, semanas_existentes,  # noqa: E402
                    detectar_semana_sesion)
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


# ----------------------------- utilidades -----------------------------

def tipo_de(ruta: Path) -> str:
    ext = ruta.suffix.lower()
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    return "desconocido"


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


# ----------------------------- aplicacion -----------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.modelo = None
        self.modelo_nombre = None
        self.cargando_modelo = False
        self.archivo = None
        self.trabajando = False
        self.ultimo_dir = None
        self.cursos = config.cargar_cursos()
        self._curso_info = None

        root.title("Transcriptor  ·  arrastra tu video o audio")
        root.geometry("760x620")
        root.minsize(640, 520)
        self._construir()

    # ---------- construccion de la interfaz ----------
    def _construir(self):
        cont = ttk.Frame(self.root, padding=16)
        cont.pack(fill="both", expand=True)

        # --- zona de arrastre ---
        self.zona = tk.Label(
            cont,
            text=("⬇  Arrastra aqui tu VIDEO o AUDIO\n\n"
                  "(o pulsa el boton para elegirlo)"),
            font=("Segoe UI", 13), justify="center",
            relief="ridge", bd=2, height=6,
            bg="#f4f6fb", fg="#33415c", cursor="hand2",
        )
        self.zona.pack(fill="x", pady=(0, 12))
        self.zona.bind("<Button-1>", lambda e: self.elegir_archivo())
        if _DND:
            self.zona.drop_target_register(DND_FILES)
            self.zona.dnd_bind("<<Drop>>", self._al_soltar)

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
        self.cbo_curso.bind("<<ComboboxSelected>>", lambda e: self._mostrar_semanas())
        ttk.Button(cur, text="➕ Curso", width=10,
                   command=self._anadir_curso).grid(
            row=2, column=3, sticky="e", pady=(6, 0))

        ttk.Label(cur, text="Semana:").grid(
            row=3, column=0, sticky="w", padx=(20, 6), pady=(6, 0))
        self.ent_semana = ttk.Entry(cur, width=8, state="disabled")
        self.ent_semana.grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Label(cur, text="Sesion:").grid(
            row=3, column=2, sticky="w", padx=(12, 6), pady=(6, 0))
        self.cbo_sesion = ttk.Combobox(
            cur, state="disabled", width=12, values=["Automatico", "1", "2"])
        self.cbo_sesion.current(0)
        self.cbo_sesion.grid(row=3, column=3, sticky="w", pady=(6, 0))

        self.lbl_curso = ttk.Label(cur, text="", foreground="#5a6472")
        self.lbl_curso.grid(row=4, column=0, columnspan=4, sticky="w",
                            padx=(20, 0), pady=(4, 0))
        self._refrescar_carpeta()

        fila_btns = ttk.Frame(cont)
        fila_btns.pack(fill="x")
        ttk.Button(fila_btns, text="📂  Elegir archivo…",
                   command=self.elegir_archivo).pack(side="left")
        self.btn_prep = ttk.Button(
            fila_btns, text="🔧  Verificar / Preparar",
            command=self.preparar_modelos)
        self.btn_prep.pack(side="left", padx=(8, 0))

        # --- estado / progreso ---
        self.lbl_info = ttk.Label(cont, text="Sin archivo.", foreground="#5a6472")
        self.lbl_info.pack(fill="x", pady=(12, 4))

        self.barra = ttk.Progressbar(cont, mode="determinate", maximum=100)
        self.barra.pack(fill="x")

        self.btn_go = ttk.Button(cont, text="▶  Transcribir",
                                 command=self.transcribir, state="disabled")
        self.btn_go.pack(anchor="w", pady=(10, 6))

        # --- resultado ---
        self.lbl_res = ttk.Label(cont, text="Resultado:", font=("Segoe UI", 10, "bold"))
        self.lbl_res.pack(anchor="w", pady=(6, 2))

        marco_txt = ttk.Frame(cont)
        marco_txt.pack(fill="both", expand=True)
        self.txt = tk.Text(marco_txt, wrap="word", font=("Consolas", 10),
                           height=10, bg="#ffffff")
        scroll = ttk.Scrollbar(marco_txt, command=self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        self.txt.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # --- botones de accion sobre el resultado ---
        acc = ttk.Frame(cont)
        acc.pack(fill="x", pady=(8, 0))
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
                     "Mientras, usa el boton 'Elegir archivo'.")

    # ---------- eventos de archivo ----------
    def _al_soltar(self, event):
        ruta = event.data.strip()
        if ruta.startswith("{") and ruta.endswith("}"):   # rutas con espacios
            ruta = ruta[1:-1]
        ruta = ruta.split("} {")[0].strip("{}")            # solo el primero
        self.cargar_archivo(Path(ruta))

    def elegir_archivo(self):
        exts = " ".join("*" + e for e in sorted(VIDEO | AUDIO))
        ruta = filedialog.askopenfilename(
            title="Elige un video o audio",
            filetypes=[("Video/Audio", exts), ("Todos", "*.*")])
        if ruta:
            self.cargar_archivo(Path(ruta))

    def cargar_archivo(self, ruta: Path):
        if self.trabajando:
            return
        if not ruta.is_file():
            messagebox.showerror("Error", f"No existe el archivo:\n{ruta}")
            return
        tipo = tipo_de(ruta)
        if tipo == "desconocido":
            messagebox.showwarning(
                "Formato no reconocido",
                f"La extension '{ruta.suffix}' no parece audio ni video.\n"
                "Se intentara igualmente.")
        self.archivo = ruta
        self.zona.config(text=f"✔  {ruta.name}")
        self._resetear_resultado()

        # duracion en segundo plano (ffprobe puede tardar un poco)
        self.lbl_info.config(text=f"Analizando '{ruta.name}'…")
        threading.Thread(target=self._analizar, args=(ruta, tipo), daemon=True).start()

    def _analizar(self, ruta, tipo):
        dur = duracion_segundos(ruta)
        corto = dur is None or dur <= UMBRAL_CORTO
        etiqueta = "video" if tipo == "video" else ("audio" if tipo == "audio" else "archivo")
        clase = "CORTO → se mostrara para copiar" if corto else "LARGO → se guardara en archivo"
        info = f"Detectado: {etiqueta}  ·  duracion {dur_bonita(dur)}  ·  {clase}"
        self.root.after(0, lambda: self._listo_para_transcribir(info))

    def _listo_para_transcribir(self, info):
        self.lbl_info.config(text=info)
        self.btn_go.config(state="normal")

    # ---------- opciones de curso ----------
    def _toggle_curso(self):
        on = self.var_curso.get()
        self.cbo_curso.config(state=("readonly" if on and self.cursos else "disabled"))
        self.ent_semana.config(state=("normal" if on else "disabled"))
        self.cbo_sesion.config(state=("readonly" if on else "disabled"))
        if on and not self.cursos:
            self.lbl_curso.config(
                text="Aun no hay cursos. Pulsa '➕ Curso' para anadir el primero.")
        elif on:
            self._mostrar_semanas()
        else:
            self.lbl_curso.config(text="")

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
                self._mostrar_semanas()

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
            self._mostrar_semanas()

    def _mostrar_semanas(self):
        if not self.cursos:
            return
        idx = self.cbo_curso.current()
        if idx < 0:
            return
        curso_dir = config.carpeta_cursos() / limpiar_nombre(self.cursos[idx]["nombre"])
        ex = semanas_existentes(curso_dir)
        if ex:
            self.lbl_curso.config(
                text=f"Semanas guardadas: {ex}   ·   vacio = automatico (la que sigue)")
        else:
            self.lbl_curso.config(
                text="Sin semanas aun.   ·   vacio = automatico (empieza en Semana 1)")

    # ---------- transcripcion ----------
    def transcribir(self):
        if self.trabajando or not self.archivo:
            return
        self._curso_info = None
        if self.var_curso.get():
            if not self.cursos:
                messagebox.showwarning(
                    "Sin cursos",
                    "Aun no hay cursos. Pulsa '➕ Curso' para anadir uno.")
                return
            idx = self.cbo_curso.current()
            ses = self.cbo_sesion.get()
            self._curso_info = {
                "curso": self.cursos[idx if idx >= 0 else 0],
                "semana_in": self.ent_semana.get().strip(),
                "sesion_in": ses if ses in ("1", "2") else "",
            }
        self.trabajando = True
        self.btn_go.config(state="disabled")
        self._resetear_resultado()
        idioma = dict(IDIOMAS)[self.cbo_idioma.get()]
        modelo_nom = dict(MODELOS)[self.cbo_modelo.get()]
        diar = self.var_diar.get()
        threading.Thread(
            target=self._trabajo, args=(self.archivo, idioma, modelo_nom, diar),
            daemon=True).start()

    # ---------- preparar / verificar modelos ----------
    def preparar_modelos(self):
        if self.trabajando:
            return
        self.trabajando = True
        self.btn_prep.config(state="disabled")
        self.btn_go.config(state="disabled")
        self.txt.delete("1.0", "end")
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
                self.btn_prep.config(state="normal")
                if self.archivo:
                    self.btn_go.config(state="normal")
            self.root.after(0, _fin)

    def _estado(self, texto, pct=None):
        def _():
            self.lbl_info.config(text=texto)
            if pct is not None:
                self.barra["value"] = pct
        self.root.after(0, _)

    def _trabajo(self, ruta, idioma, modelo_nom, diar):
        try:
            # 1) cargar modelo (una vez, o si cambio de calidad)
            if self.modelo is None or self.modelo_nombre != modelo_nom:
                self._estado(f"Cargando modelo {modelo_nom} (la 1a vez descarga datos)…", 0)
                self.modelo, *_ = T.cargar_modelo(modelo_nom)
                self.modelo_nombre = modelo_nom

            sd = None
            if diar:
                if setup_modelos.faltan_modelos():
                    self._estado("Descargando modelos de hablantes (solo la 1a vez)…", 0)
                    setup_modelos.verificar_y_descargar(
                        log=lambda m: self._estado(m))
                self._estado("Cargando identificador de hablantes…", 0)
                sd = T.cargar_diarizador(0)

            # 2) transcribir con progreso
            self._estado("Transcribiendo…", 0)
            dur = duracion_segundos(ruta) or 0
            seg_iter, info = self.modelo.transcribe(
                str(ruta), language=idioma, vad_filter=True, beam_size=5,
                word_timestamps=bool(sd))
            total = getattr(info, "duration", 0) or dur or 0

            segmentos = []
            t0 = time.time()
            for seg in seg_iter:
                segmentos.append({
                    "start": round(seg.start, 3), "end": round(seg.end, 3),
                    "text": seg.text.strip(), "words": None})
                if total:
                    pct = min(100, seg.end / total * 100)
                    self._estado(f"Transcribiendo…  {pct:4.0f}%", pct)

            # 3) diarizacion opcional
            if sd is not None:
                self._estado("Identificando hablantes…", 100)
                diar_segs = T.diarizar(sd, ruta)
                for seg in segmentos:
                    seg["speaker"] = (T.hablante_de(seg["start"], seg["end"], diar_segs)
                                      if diar_segs else None)

            tardo = time.time() - t0
            corto = (total or 0) <= UMBRAL_CORTO
            self.root.after(0, lambda: self._mostrar_resultado(
                ruta, segmentos, corto, tardo, idioma, diar))
        except Exception as e:
            self.root.after(0, lambda err=e: self._error(err))
        finally:
            self.root.after(0, self._fin_trabajo)

    def _mostrar_resultado(self, ruta, segmentos, corto, tardo, idioma, diar):
        texto = texto_de_segmentos(segmentos)
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", texto)
        self.btn_copiar.config(state="normal")
        self.barra["value"] = 100

        # modo curso: guarda ordenado en Escritorio\Cursos sin importar la duracion
        if self._curso_info:
            self._guardar_en_curso(segmentos, tardo)
            return

        if corto:
            self.lbl_res.config(text=f"Resultado (listo para copiar · {T.mmss(tardo)}):")
            self.lbl_info.config(
                text="✓ Transcripcion corta lista. Copia el texto o guardalo si quieres.")
            self.btn_guardar.config(state="normal")
        else:
            # archivo largo: guardar automaticamente txt + srt
            nombre = limpiar_nombre(ruta.stem) or "transcripcion"
            destino_dir = CARPETA_SALIDA / nombre
            destino_dir.mkdir(parents=True, exist_ok=True)
            base = destino_dir / nombre
            T.guardar(segmentos, base, ["txt", "srt"])
            self.ultimo_dir = destino_dir
            self.lbl_res.config(text=f"Vista previa (guardado · {T.mmss(tardo)}):")
            self.lbl_info.config(
                text=f"✓ LISTO. Guardado en:  {base.with_suffix('.txt')}   (+ .srt)")
            self.btn_guardar.config(state="normal")
            self.btn_carpeta.config(state="normal")

    def _guardar_en_curso(self, segmentos, tardo):
        info = self._curso_info
        curso = info["curso"]
        curso_dir = config.carpeta_cursos() / limpiar_nombre(curso["nombre"])
        semana, sesion = detectar_semana_sesion(
            curso_dir, info["semana_in"], info["sesion_in"])
        destino_dir = curso_dir / f"Semana {semana}"
        destino_dir.mkdir(parents=True, exist_ok=True)
        base = destino_dir / f"sesion{sesion}"
        T.guardar(segmentos, base, ["txt", "srt"])
        self.ultimo_dir = destino_dir
        self.lbl_res.config(text=f"Guardado en el curso ({T.mmss(tardo)}):")
        self.lbl_info.config(
            text=(f"✓ {curso['nombre']}  ->  Semana {semana} / sesion{sesion}\n"
                  f"{base.with_suffix('.txt')}   (+ .srt)"))
        self.btn_guardar.config(state="normal")
        self.btn_carpeta.config(state="normal")
        self._mostrar_semanas()

    def _error(self, e):
        self.barra["value"] = 0
        self.lbl_info.config(text=f"✗ Error: {e}")
        messagebox.showerror("Error al transcribir", str(e))

    def _fin_trabajo(self):
        self.trabajando = False
        if self.archivo:
            self.btn_go.config(state="normal")

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
        nombre = (limpiar_nombre(self.archivo.stem) if self.archivo else "transcripcion")
        ruta = filedialog.asksaveasfilename(
            title="Guardar transcripcion",
            defaultextension=".txt", initialfile=f"{nombre}.txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")])
        if ruta:
            Path(ruta).write_text(texto, encoding="utf-8")
            self.ultimo_dir = Path(ruta).parent
            self.btn_carpeta.config(state="normal")
            self.lbl_info.config(text=f"💾 Guardado en: {ruta}")

    def abrir_carpeta(self):
        carpeta = self.ultimo_dir or CARPETA_SALIDA
        try:
            os.startfile(str(carpeta))       # Windows
        except AttributeError:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(carpeta)])

    # ---------- varios ----------
    def _resetear_resultado(self):
        self.txt.delete("1.0", "end")
        self.barra["value"] = 0
        self.lbl_res.config(text="Resultado:")
        for b in (self.btn_copiar, self.btn_guardar, self.btn_carpeta):
            b.config(state="disabled")


def lanzar():
    root = TkinterDnD.Tk() if _DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    lanzar()
