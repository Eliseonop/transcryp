"""
Traductor en vivo (ingles -> espanol): la ventana de la herramienta.

- Escucha lo que suena en el PC (un video, una clase, una reunion…) o un
  microfono, lo transcribe con Whisper y lo traduce al espanol al momento.
- Se ve en dos columnas: a la izquierda lo que se escucha (ingles) y al lado la
  traduccion. Mientras alguien habla, la frase en curso aparece en gris.
- Todo el texto se puede seleccionar con el raton (cuantas frases quieras, de
  cualquiera de los dos lados) y copiar con Ctrl+C o con el clic derecho.
- Tambien traduce un archivo de audio/video entero (boton o arrastrandolo) y
  guarda los subtitulos en espanol (.srt) o el texto bilingue (.txt).

Se abre desde la ventana principal con el boton "🌐 Traductor en vivo".
"""
from __future__ import annotations

import math
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

import transcribir as T  # noqa: E402
from app import config, en_vivo, traductor  # noqa: E402

# Calidad de Whisper para la escucha: etiqueta -> modelo
CALIDADES = [
    ("Equilibrado (medium)", "medium"),
    ("Rapido (small)", "small"),
    ("Maxima calidad (large-v3)", "large-v3"),
    ("Muy rapido (base)", "base"),
]

# Colores de la tabla
CAB_BG = "#e8edf7"
FONDO = "#ffffff"
SEPARADOR = "#dfe4ee"        # lineas finas entre columnas
COLOR_EN = "#1f2a44"
COLOR_ES = "#0b3d91"
COLOR_GRIS = "#8a94a6"
COLOR_ERROR = "#b3261e"

AYUDA_VACIA = ("Pulsa ▶ Escuchar y reproduce un video en ingles (o habla al "
               "microfono).\nAqui veras lo que se escucha y, al lado, la traduccion.\n\n"
               "Tambien puedes traducir un archivo entero con 📂 o arrastrandolo aqui.\n\n"
               "Selecciona con el raton las frases que quieras (de cualquier lado)\n"
               "y copialas con Ctrl+C o con el clic derecho.")


def _hms(seg: float) -> str:
    s = int(seg)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _hay_gpu() -> bool:
    try:
        T._cargar_dlls_cuda()
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class _Cancelado(Exception):
    pass


# ----------------------------- tabla bilingue -----------------------------

ESTILOS = ("tiempo", "en", "es", "gris", "error")


def _alto_px(t, i1, i2) -> int:
    """Alto en pixeles del texto entre i1 e i2 (recalcula lo necesario)."""
    try:
        return int(t.tk.call(t._w, "count", "-update", "-ypixels", i1, i2))
    except (tk.TclError, ValueError):
        return 0


def _linea(indice: str) -> int:
    return int(str(indice).split(".")[0])


class TablaBilingue(ttk.Frame):
    """Tabla tiempo | ingles | espanol con el texto SELECCIONABLE.

    Cada columna es un cuadro de texto (tk.Text) de solo lectura: se puede
    seleccionar con el raton cuanto se quiera (una palabra, una frase o muchas
    seguidas, del lado en ingles o del traducido) y copiarlo con Ctrl+C o con
    el clic derecho.

    Las tres columnas se desplazan juntas y cada fila mide lo mismo en las tres:
    a la columna mas baja se le anade espacio debajo de la frase (spacing3)
    hasta igualar a la mas alta. La fila n es la linea n de las tres columnas;
    la frase en curso (gris), si la hay, es la ultima."""

    MAX_FILAS = 300      # filas en pantalla (las mas viejas salen solo de la vista)
    AIRE = 10            # px de separacion entre filas

    def __init__(self, master, fuentes, al_menu, al_copiar=None):
        super().__init__(master)
        self.f = fuentes
        self.al_menu = al_menu           # al_menu(evento, cuadro, fid, seleccion, fids)
        self.al_copiar = al_copiar       # aviso tras copiar con Ctrl+C
        self._seq_de = {}                # fid -> numero de orden
        self._fid_de = {}                # numero de orden -> fid
        self._seq_ini = 0                # numero de orden de la fila de la linea 1
        self._seq_sig = 0
        self._n = 0                      # filas terminadas en pantalla
        self._parcial = False            # hay frase en curso (linea n + 1)
        self._sp = {}                    # cuadro -> tags de espacio ya creados
        self._esperado = {}              # cuadro -> posicion puesta por programa
        self._anchos = {}
        self._job = None
        self._arrastrando = False

        self.cuerpo = tk.Frame(self, bg=SEPARADOR)
        self.cuerpo.pack(fill="both", expand=True)
        titulos = ("Tiempo", "Lo que se escucha (ingles)", "Traduccion (espanol)")
        for col, txt in enumerate(titulos):
            tk.Label(self.cuerpo, text=txt, bg=CAB_BG, fg="#33415c",
                     font=fuentes["cab"], anchor="w", padx=8, pady=6).grid(
                row=0, column=col, sticky="ew", padx=(0, 1), pady=(0, 1))
        tk.Frame(self.cuerpo, bg=CAB_BG).grid(row=0, column=3, sticky="nsew", pady=(0, 1))

        self.txt_t = self._cuadro(ancho=8, ajuste="none")
        self.txt_en = self._cuadro(ancho=20, ajuste="word")
        self.txt_es = self._cuadro(ancho=20, ajuste="word")
        self.cols = (self.txt_t, self.txt_en, self.txt_es)
        for col, t in enumerate(self.cols):
            t.grid(row=1, column=col, sticky="nsew", padx=(0, 1))
        self.barra = ttk.Scrollbar(self.cuerpo, orient="vertical", command=self._yview)
        self.barra.grid(row=1, column=3, sticky="ns")
        self.cuerpo.rowconfigure(1, weight=1)
        self.cuerpo.columnconfigure(1, weight=1, uniform="texto")
        self.cuerpo.columnconfigure(2, weight=1, uniform="texto")

        self.vacio = tk.Label(self.cuerpo, text=AYUDA_VACIA, bg=FONDO, fg=COLOR_GRIS,
                              font=fuentes["tiempo"], justify="center")
        self.vacio.place(relx=0.5, rely=0.55, anchor="center")

    def _cuadro(self, ancho, ajuste):
        t = tk.Text(self.cuerpo, width=ancho, height=8, wrap=ajuste,
                    font=self.f["tiempo"], bg=FONDO, fg=COLOR_EN, bd=0,
                    highlightthickness=0, padx=8, pady=6, cursor="xterm",
                    insertwidth=0, takefocus=0, selectbackground="#cfe0ff",
                    selectforeground=COLOR_EN, inactiveselectbackground="#dde6f5")
        t.tag_configure("tiempo", font=self.f["tiempo"], foreground=COLOR_GRIS)
        t.tag_configure("en", font=self.f["en"], foreground=COLOR_EN)
        t.tag_configure("es", font=self.f["es"], foreground=COLOR_ES)
        t.tag_configure("gris", font=self.f["parcial"], foreground=COLOR_GRIS)
        t.tag_configure("error", font=self.f["es"], foreground=COLOR_ERROR)
        # solo lectura: se puede seleccionar y copiar, pero no escribir
        t.configure(state="disabled",
                    yscrollcommand=lambda a, b, t=t: self._al_desplazar(t, a, b))
        t.bind("<MouseWheel>", self._rueda)
        t.bind("<Button-3>", lambda e, t=t: self._menu(e, t))
        t.bind("<<SelectAll>>", lambda e, t=t: self.seleccionar_todo(t))
        t.bind("<<Copy>>", lambda e, t=t: self._copiado(t))
        t.bind("<ButtonPress-1>", lambda e: self._arrastre(True))
        t.bind("<ButtonRelease-1>", lambda e: self._arrastre(False))
        t.bind("<Configure>", self._al_cambiar_tamano)
        return t

    # ---------- API ----------
    def destinos(self):
        """Widgets donde se puede soltar un archivo para traducirlo."""
        return (*self.cols, self.vacio)

    def agregar(self, fid, tiempo, en, es_provisional=None):
        """Frase terminada. Mientras llega la traduccion se ve la provisional (gris)."""
        abajo = self._esta_abajo()
        self._quitar_parcial()
        self.vacio.place_forget()
        self._anadir(self.txt_t, tiempo, "tiempo")
        self._anadir(self.txt_en, en, "en")
        self._anadir(self.txt_es, es_provisional or "…", "gris")
        self._seq_de[fid] = self._seq_sig
        self._fid_de[self._seq_sig] = fid
        self._seq_sig += 1
        self._n += 1
        self._alinear(self._n)
        if self._n > self.MAX_FILAS:
            self._quitar_primera()
        if abajo:
            self._bajar()

    def poner_es(self, fid, texto, error=False):
        linea = self._linea_de(fid)
        if linea is None:                # ya salio de la vista
            return
        abajo = self._esta_abajo()
        self._cambiar(self.txt_es, linea, texto, "error" if error else "es")
        self._alinear(linea)
        if abajo:
            self._bajar()

    def mostrar_parcial(self, en):
        """Frase en curso (gris, al final). None la quita."""
        if not en:
            self._quitar_parcial()
            return
        abajo = self._esta_abajo()
        linea = self._n + 1
        if self._parcial:
            self._cambiar(self.txt_en, linea, en, "gris")
        else:
            self.vacio.place_forget()
            self._anadir(self.txt_t, "…", "tiempo")
            self._anadir(self.txt_en, en, "gris")
            self._anadir(self.txt_es, "", "gris")
            self._parcial = True
        self._alinear(linea)
        if abajo:
            self._bajar()

    def poner_es_parcial(self, texto):
        if self._parcial:
            abajo = self._esta_abajo()
            self._cambiar(self.txt_es, self._n + 1, texto, "gris")
            self._alinear(self._n + 1)
            if abajo:
                self._bajar()

    def limpiar(self):
        for t in self.cols:
            t.configure(state="normal")
            t.delete("1.0", "end")
            t.configure(state="disabled")
        self._seq_de.clear()
        self._fid_de.clear()
        self._seq_ini = self._seq_sig
        self._n = 0
        self._parcial = False
        self.vacio.place(relx=0.5, rely=0.55, anchor="center")

    def seleccionar_todo(self, t):
        t.tag_remove("sel", "1.0", "end")
        t.tag_add("sel", "1.0", "end-1c")
        t.focus_set()
        return "break"

    def filas_seleccionadas(self, t) -> list:
        """fids de las filas que toca la seleccion del cuadro t."""
        rango = t.tag_ranges("sel")
        if not rango:
            return []
        l1, fin = _linea(t.index(rango[0])), t.index(rango[-1])
        l2 = _linea(fin) - (1 if fin.endswith(".0") else 0)
        fids = (self._fid_en_linea(n) for n in range(l1, l2 + 1))
        return [f for f in fids if f is not None]

    def realinear(self):
        """Vuelve a igualar todas las filas (al cambiar el ancho o la letra)."""
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(120, self._realinear_ya)

    # ---------- texto ----------
    @staticmethod
    def _anadir(t, texto, estilo):
        t.configure(state="normal")
        t.insert("end", " ".join(str(texto).split()) + "\n", estilo)
        t.configure(state="disabled")

    @staticmethod
    def _cambiar(t, linea, texto, estilo):
        i1, i2 = f"{linea}.0", f"{linea + 1}.0"
        t.configure(state="normal")
        t.delete(i1, f"{linea}.end")
        t.insert(i1, " ".join(str(texto).split()))
        for nombre in ESTILOS:           # el estilo cubre tambien el salto de linea
            t.tag_remove(nombre, i1, i2)
        t.tag_add(estilo, i1, i2)
        t.configure(state="disabled")

    def _quitar_parcial(self):
        if self._parcial:
            linea = self._n + 1
            for t in self.cols:
                t.configure(state="normal")
                t.delete(f"{linea}.0", f"{linea + 1}.0")
                t.configure(state="disabled")
            self._parcial = False

    def _quitar_primera(self):
        for t in self.cols:
            t.configure(state="normal")
            t.delete("1.0", "2.0")
            t.configure(state="disabled")
        fid = self._fid_de.pop(self._seq_ini, None)
        self._seq_de.pop(fid, None)
        self._seq_ini += 1
        self._n -= 1

    def _linea_de(self, fid):
        seq = self._seq_de.get(fid)
        return None if seq is None else seq - self._seq_ini + 1

    def _fid_en_linea(self, linea):
        if 1 <= linea <= self._n:
            return self._fid_de.get(self._seq_ini + linea - 1)
        return None

    # ---------- alinear las filas ----------
    def _alinear(self, linea):
        """Iguala la altura de la fila 'linea' en las tres columnas."""
        i1, i2 = f"{linea}.0", f"{linea + 1}.0"
        alturas = []
        for t in self.cols:
            for nombre in set(t.tag_names(i1)) | set(t.tag_names(f"{linea}.end")):
                if nombre.startswith("sp"):
                    t.tag_remove(nombre, i1, i2)
            alturas.append(_alto_px(t, i1, i2))
        alto = max(alturas)
        for t, h in zip(self.cols, alturas):
            px = alto - h + self.AIRE
            nombre = f"sp{px}"
            creados = self._sp.setdefault(str(t), set())
            if nombre not in creados:        # configurar un tag ya usado es lento
                t.tag_configure(nombre, spacing3=px)
                creados.add(nombre)
            t.tag_add(nombre, i1, i2)

    def _realinear_ya(self):
        self._job = None
        abajo = self._esta_abajo()
        for linea in range(1, self._n + (2 if self._parcial else 1)):
            self._alinear(linea)
        if abajo:
            self._bajar()
        else:
            self._seguir(self.txt_en, self.txt_en.yview()[0])

    def _al_cambiar_tamano(self, e):
        if self._anchos.get(str(e.widget)) != e.width:
            self._anchos[str(e.widget)] = e.width
            self.realinear()

    # ---------- desplazamiento (las tres columnas juntas) ----------
    def _esta_abajo(self) -> bool:
        return not self._arrastrando and self.txt_en.yview()[1] >= 0.999

    def _bajar(self):
        for t in self.cols:
            t.yview_moveto(1.0)

    def _yview(self, *args):             # barra de desplazamiento
        for t in self.cols:
            t.yview(*args)

    def _rueda(self, e):
        px = -int(e.delta / 120 * 48) or (-48 if e.delta > 0 else 48)
        for t in self.cols:
            t.yview_scroll(px, "pixels")
        return "break"

    def _seguir(self, origen, primero):
        """Pone las otras columnas a la misma altura que 'origen'."""
        for t in self.cols:
            if t is not origen and abs(t.yview()[0] - primero) > 1e-6:
                self._esperado[t] = primero
                t.yview_moveto(primero)
        self.after_idle(self._esperado.clear)

    def _al_desplazar(self, origen, primero, ultimo):
        self.barra.set(primero, ultimo)
        primero = float(primero)
        esperado = self._esperado.pop(origen, None)
        if esperado is not None and abs(primero - esperado) < 1e-3:
            return                        # eco de un movimiento hecho por programa
        # la columna se movio sola (seleccionando con el raton, teclado…)
        self._seguir(origen, primero)

    # ---------- raton ----------
    def _arrastre(self, pulsado):
        self._arrastrando = pulsado

    def _copiado(self, t):
        if self.al_copiar and t.tag_ranges("sel"):
            self.after_idle(self.al_copiar)

    def _menu(self, e, t):
        fid = self._fid_en_linea(_linea(t.index(f"@{e.x},{e.y}")))
        try:
            seleccion = t.get("sel.first", "sel.last")
        except tk.TclError:
            seleccion = ""
        self.al_menu(e, t, fid, seleccion, self.filas_seleccionadas(t))
        return "break"


# ----------------------------- ventana -----------------------------

class VentanaTraductor:
    def __init__(self, app, extensiones, carpeta_salida, dnd=False):
        self.app = app
        self.root = app.root
        self.extensiones = extensiones
        self.carpeta_salida = carpeta_salida

        self.cerrada = False
        self.fuentes = []            # [(etiqueta, fuente)] de en_vivo.listar_fuentes
        self.escucha = None          # en_vivo.Escucha en marcha
        self.ocupado = False         # cargando modelo / escuchando / traduciendo archivo
        self.cancelar = False
        self.modo = None             # "vivo" | "archivo"
        self.filas = {}              # fid -> {"ini", "fin", "en", "es"}
        self._fid = 0
        self._t_base = 0.0           # las sesiones nuevas siguen el tiempo de las anteriores
        self._gen_final = 0          # sube con cada frase terminada
        self._es_parcial = None      # traduccion de la frase en curso
        self._sin_guardar = False
        self._hubo_error = False
        self._ultimo_sonido = 0.0
        self._aviso_silencio = False
        self._archivo = None         # archivo traducido (para nombrar lo que se guarda)
        self._modelo_propio = None   # (nombre, modelo, device) si no se comparte el de la app
        self._estado_fijo = ("", False)
        self._job_estado = None
        self.q_trad = queue.Queue()

        prefs = config.preferencia("traductor", {})
        self.prefs = prefs if isinstance(prefs, dict) else {}
        self.motor = self.prefs.get("motor", "local")
        if self.motor not in {v for _, v in traductor.MOTORES}:
            self.motor = "local"
        self.tam = int(self.prefs.get("tam", 11))

        self.win = tk.Toplevel(self.root)
        self.win.title("Traductor en vivo  ·  ingles → espanol")
        self.win.geometry("1040x660")
        self.win.minsize(780, 480)
        self.win.protocol("WM_DELETE_WINDOW", self.cerrar)
        self._construir(dnd)
        self._actualizar_botones()

        threading.Thread(target=self._hilo_traduccion, daemon=True).start()
        if self.motor == "local":
            if traductor.falta_modelo_local():
                self._aviso("Preparando el traductor local (se descarga ~90 MB, "
                            "solo la primera vez)…")
            self.q_trad.put(("preparar",))
        self._cargar_fuentes()

    # ---------- construccion ----------
    def _construir(self, dnd):
        self.fuentes_tk = {
            "cab": tkfont.Font(root=self.win, family="Segoe UI", size=10, weight="bold"),
            "tiempo": tkfont.Font(root=self.win, family="Segoe UI", size=9),
            "en": tkfont.Font(root=self.win, family="Segoe UI", size=self.tam),
            "es": tkfont.Font(root=self.win, family="Segoe UI", size=self.tam),
            "parcial": tkfont.Font(root=self.win, family="Segoe UI", size=self.tam,
                                   slant="italic"),
        }
        cont = ttk.Frame(self.win, padding=12)
        cont.pack(fill="both", expand=True)

        # --- opciones ---
        ops = ttk.Frame(cont)
        ops.pack(fill="x")
        ttk.Label(ops, text="Escuchar:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.cbo_fuente = ttk.Combobox(ops, state="disabled", width=60)
        self.cbo_fuente.grid(row=0, column=1, columnspan=3, sticky="we")
        self.cbo_fuente.bind("<<ComboboxSelected>>", lambda e: self._guardar_prefs())
        self.btn_refrescar = ttk.Button(ops, text="⟳", width=3, command=self._cargar_fuentes)
        self.btn_refrescar.grid(row=0, column=4, padx=(6, 0))

        ttk.Label(ops, text="Calidad:").grid(row=1, column=0, sticky="w",
                                             padx=(0, 6), pady=(8, 0))
        self.cbo_calidad = ttk.Combobox(ops, state="readonly", width=26,
                                        values=[e for e, _ in CALIDADES])
        nombres = [v for _, v in CALIDADES]
        calidad = self.prefs.get("calidad") or ("medium" if _hay_gpu() else "small")
        self.cbo_calidad.current(nombres.index(calidad) if calidad in nombres else 0)
        self.cbo_calidad.grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.cbo_calidad.bind("<<ComboboxSelected>>", lambda e: self._guardar_prefs())

        ttk.Label(ops, text="Traductor:").grid(row=1, column=2, sticky="e",
                                               padx=(18, 6), pady=(8, 0))
        self.cbo_motor = ttk.Combobox(ops, state="readonly", width=32,
                                      values=[e for e, _ in traductor.MOTORES])
        self.cbo_motor.current([v for _, v in traductor.MOTORES].index(self.motor))
        self.cbo_motor.grid(row=1, column=3, sticky="w", pady=(8, 0))
        self.cbo_motor.bind("<<ComboboxSelected>>", self._motor_cambiado)
        ops.columnconfigure(3, weight=1)

        # --- botones ---
        bot = ttk.Frame(cont)
        bot.pack(fill="x", pady=(10, 0))
        self.btn_escuchar = ttk.Button(bot, text="▶  Escuchar", command=self.escuchar)
        self.btn_escuchar.pack(side="left")
        self.btn_detener = ttk.Button(bot, text="⏹  Detener", command=self.detener)
        self.btn_detener.pack(side="left", padx=(8, 0))
        self.btn_archivo = ttk.Button(bot, text="📂  Traducir un archivo…",
                                      command=self.traducir_archivo)
        self.btn_archivo.pack(side="left", padx=(8, 0))

        ttk.Button(bot, text="A+", width=3,
                   command=lambda: self._tam_letra(+1)).pack(side="right")
        ttk.Button(bot, text="A−", width=3,
                   command=lambda: self._tam_letra(-1)).pack(side="right", padx=(0, 4))
        self.var_encima = tk.BooleanVar(value=False)
        ttk.Checkbutton(bot, text="Siempre visible", variable=self.var_encima,
                        command=lambda: self.win.attributes(
                            "-topmost", self.var_encima.get())).pack(
            side="right", padx=(0, 12))

        # --- estado ---
        est = ttk.Frame(cont)
        est.pack(fill="x", pady=(10, 0))
        self.lbl_estado = ttk.Label(est, text="", foreground="#5a6472")
        self.lbl_estado.pack(side="left", fill="x", expand=True)
        self.barra = ttk.Progressbar(est, length=140, maximum=100)
        self.barra.pack(side="right")
        self.lbl_barra = ttk.Label(est, text="Nivel", foreground="#5a6472")
        self.lbl_barra.pack(side="right", padx=(0, 6))
        self.lbl_aviso = ttk.Label(cont, text="", foreground="#b45309")
        self.lbl_aviso.pack(fill="x", pady=(2, 0))

        # --- tabla ---
        self.tabla = TablaBilingue(
            cont, self.fuentes_tk, self._menu_fila,
            al_copiar=lambda: self._estado_temporal("📋 Seleccion copiada al portapapeles."))
        self.tabla.pack(fill="both", expand=True, pady=(6, 0))

        # --- acciones (antes que la tabla para que nunca queden cortadas) ---
        acc = ttk.Frame(cont)
        acc.pack(side="bottom", fill="x", pady=(8, 0), before=self.tabla)
        ttk.Label(acc, text="Copiar todo:").pack(side="left", padx=(0, 6))
        self.btn_cop_es = ttk.Button(acc, text="📋 Espanol",
                                     command=lambda: self.copiar("es"))
        self.btn_cop_es.pack(side="left")
        self.btn_cop_en = ttk.Button(acc, text="📋 Ingles",
                                     command=lambda: self.copiar("en"))
        self.btn_cop_en.pack(side="left", padx=(6, 0))
        self.btn_cop_ambos = ttk.Button(acc, text="📋 Ambos",
                                        command=lambda: self.copiar("ambos"))
        self.btn_cop_ambos.pack(side="left", padx=(6, 0))
        self.btn_txt = ttk.Button(acc, text="💾 Guardar texto…", command=self.guardar_texto)
        self.btn_txt.pack(side="left", padx=(16, 0))
        self.btn_srt = ttk.Button(acc, text="💬 Subtitulos en espanol (.srt)…",
                                  command=self.guardar_srt)
        self.btn_srt.pack(side="left", padx=(6, 0))
        self.btn_limpiar = ttk.Button(acc, text="🧹 Limpiar", command=self.limpiar)
        self.btn_limpiar.pack(side="right")

        if dnd:
            try:
                from tkinterdnd2 import DND_FILES
                for w in self.tabla.destinos():
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._al_soltar)
            except Exception:
                pass

    # ---------- utilidades de la ventana ----------
    def viva(self) -> bool:
        return not self.cerrada

    def traer(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def _ui(self, fn, *args):
        """Ejecuta fn en el hilo de Tk (se puede llamar desde cualquier hilo)."""
        if self.cerrada:
            return
        try:
            self.root.after(0, lambda: None if self.cerrada else fn(*args))
        except (RuntimeError, tk.TclError):
            pass                      # la app se esta cerrando

    def _estado(self, texto, error=False):
        self._estado_fijo = (texto, error)
        if self._job_estado is None:
            self.lbl_estado.config(text=texto,
                                   foreground=COLOR_ERROR if error else "#5a6472")

    def _estado_temporal(self, texto):
        """Mensaje corto (p. ej. 'Copiado') que luego deja el estado como estaba."""
        if self._job_estado:
            self.win.after_cancel(self._job_estado)
        self.lbl_estado.config(text=texto, foreground="#1e7b34")

        def volver():
            self._job_estado = None
            self._estado(*self._estado_fijo)
        self._job_estado = self.win.after(2500, volver)

    def _aviso(self, texto, error=False):
        self.lbl_aviso.config(text=texto, foreground=COLOR_ERROR if error else "#b45309")

    def _tam_letra(self, delta):
        self.tam = max(8, min(24, self.tam + delta))
        for k in ("en", "es", "parcial"):
            self.fuentes_tk[k].configure(size=self.tam)
        self.tabla.realinear()
        self._guardar_prefs()

    def _fuente_elegida(self):
        idx = self.cbo_fuente.current()
        return self.fuentes[idx][1] if self.fuentes and idx >= 0 else None

    def _guardar_prefs(self):
        self.prefs.update({
            "fuente": self._fuente_elegida() or self.prefs.get("fuente"),
            "calidad": dict(CALIDADES)[self.cbo_calidad.get()],
            "motor": self.motor, "tam": self.tam})
        try:
            config.guardar_preferencia("traductor", self.prefs)
        except Exception:
            pass

    def _actualizar_botones(self):
        libre = not self.ocupado
        self.btn_escuchar.config(state="normal" if libre and self.fuentes else "disabled")
        self.btn_archivo.config(state="normal" if libre else "disabled")
        self.btn_detener.config(state="disabled" if libre or self.cancelar else "normal")
        self.btn_refrescar.config(state="normal" if libre else "disabled")
        self.cbo_calidad.config(state="readonly" if libre else "disabled")
        self.cbo_fuente.config(state="readonly" if libre and self.fuentes else "disabled")
        hay = "normal" if self.filas else "disabled"
        for b in (self.btn_cop_es, self.btn_cop_en, self.btn_cop_ambos,
                  self.btn_txt, self.btn_srt):
            b.config(state=hay)
        archivo_en_marcha = self.ocupado and self.modo == "archivo"
        self.btn_limpiar.config(state="disabled" if archivo_en_marcha else hay)

    # ---------- fuentes de audio ----------
    def _cargar_fuentes(self):
        self.fuentes = []
        self.cbo_fuente.config(values=["Buscando fuentes de audio…"])
        self.cbo_fuente.current(0)
        self._actualizar_botones()

        def trabajo():
            try:
                res, err = en_vivo.listar_fuentes(), None
            except Exception as e:
                res, err = [], e
            self._ui(self._fuentes_listas, res, err)
        threading.Thread(target=trabajo, daemon=True).start()

    def _fuentes_listas(self, fuentes, err):
        self.fuentes = fuentes
        if not fuentes:
            self.cbo_fuente.config(values=["(no hay ninguna fuente de audio)"])
            self.cbo_fuente.current(0)
            self._estado(f"✗ No se pudieron listar las fuentes de audio: {err}" if err
                         else "✗ No se encontro ningun altavoz ni microfono.", error=True)
        else:
            self.cbo_fuente.config(values=[e for e, _ in fuentes])
            guardada = self.prefs.get("fuente") or {}
            idx = next((i for i, (_, f) in enumerate(fuentes) if f == guardada), 0)
            self.cbo_fuente.current(idx)
            if not self.ocupado:
                self._estado("Elige que escuchar y pulsa ▶ Escuchar. "
                             "'Lo que suena en el PC' capta videos, clases o reuniones.")
        self._actualizar_botones()

    # ---------- modelo de Whisper ----------
    def _obtener_modelo(self, nombre):
        """Usa el modelo ya cargado en la ventana principal si es el mismo; si no,
        carga uno propio (se libera al cerrar el traductor)."""
        app = self.app
        if app.modelo is not None and app.modelo_nombre == nombre:
            return app.modelo, app.modelo_device
        if self._modelo_propio and self._modelo_propio[0] == nombre:
            return self._modelo_propio[1], self._modelo_propio[2]
        self._ui(self._estado, f"Cargando el modelo {nombre} "
                               "(la 1a vez se descarga, puede tardar)…")
        self._modelo_propio = None              # liberar el anterior antes
        modelo, device, _ = T.cargar_modelo(nombre)
        self._modelo_propio = (nombre, modelo, device)
        return modelo, device

    # ---------- escuchar en vivo ----------
    def _empezar(self, modo):
        self.ocupado, self.cancelar, self.modo = True, False, modo
        self._hubo_error = False
        self._aviso_silencio = False
        self._ultimo_sonido = time.monotonic()
        self.lbl_barra.config(text="Nivel" if modo == "vivo" else "Progreso")
        self.barra["value"] = 0
        self._guardar_prefs()
        self._actualizar_botones()

    def escuchar(self):
        fuente = self._fuente_elegida()
        if self.ocupado or fuente is None:
            return
        nombre = dict(CALIDADES)[self.cbo_calidad.get()]
        self._t_base = max((f["fin"] for f in self.filas.values()), default=0.0)
        self._empezar("vivo")
        self._estado("Preparando…")
        threading.Thread(target=self._trabajo_vivo, args=(nombre, fuente),
                         daemon=True).start()

    def _trabajo_vivo(self, nombre, fuente):
        try:
            modelo, _ = self._obtener_modelo(nombre)
            if self.cancelar:
                raise _Cancelado()
            self._ui(self._estado, "Abriendo el audio…")
            esc = en_vivo.Escucha(modelo, fuente, self._evento)
            self.escucha = esc
            esc.iniciar()
            if self.cancelar:             # pulsaron Detener mientras arrancaba
                esc.detener()
        except _Cancelado:
            self._evento("fin", None)
        except Exception as e:
            self._evento("error", f"No se pudo preparar el modelo: {e}")
            self._evento("fin", None)

    def detener(self):
        if not self.ocupado:
            return
        self.cancelar = True
        if self.escucha is not None:
            self.escucha.detener()
        self._estado("⏹ Deteniendo…")
        self._actualizar_botones()

    # ---------- eventos de la escucha / del archivo ----------
    def _evento(self, tipo, datos):
        """Llega desde los hilos de trabajo: se pasa al hilo de Tk."""
        self._ui(self._evento_ui, tipo, datos)

    def _evento_ui(self, tipo, datos):
        if tipo == "nivel":
            self._nivel(datos)
        elif tipo == "escuchando":
            self._estado("🎧 Escuchando… reproduce algo en ingles (o habla). "
                         "Pulsa ⏹ Detener para parar.")
        elif tipo == "parcial":
            self.tabla.mostrar_parcial(datos)
            if datos:
                self.q_trad.put(("parcial", self._gen_final, datos))
            else:
                self._es_parcial = None
        elif tipo == "final":
            self._final(datos)
        elif tipo == "progreso":
            self.barra["value"] = datos
        elif tipo == "estado":
            self._estado(datos)
        elif tipo == "error":
            self._hubo_error = True
            self._estado("✗ " + datos, error=True)
        elif tipo == "fin":
            self._terminado(datos)

    def _nivel(self, rms):
        if self.modo != "vivo" or not self.ocupado:
            return
        db = 20 * math.log10(rms + 1e-9)
        self.barra["value"] = max(0.0, min(100.0, (db + 60) * 100 / 60))
        ahora = time.monotonic()
        if rms > 0.003:
            self._ultimo_sonido = ahora
            if self._aviso_silencio:
                self._aviso_silencio = False
                self._evento_ui("escuchando", None)
        elif not self._aviso_silencio and ahora - self._ultimo_sonido > 8:
            self._aviso_silencio = True
            self._estado("🎧 Escuchando… pero no llega sonido. ¿Esta sonando algo? "
                         "Revisa la fuente elegida en 'Escuchar'.")

    def _final(self, d):
        self._gen_final += 1
        self._fid += 1
        fid = self._fid
        ini, fin = d["ini"] + self._t_base, d["fin"] + self._t_base
        self.filas[fid] = {"ini": ini, "fin": fin, "en": d["texto"], "es": None}
        provisional = self._es_parcial if self.modo == "vivo" else None
        self.tabla.agregar(fid, _hms(ini), d["texto"], provisional)
        self._es_parcial = None
        self._sin_guardar = True
        self.q_trad.put(("final", fid, d["texto"]))
        if len(self.filas) == 1:
            self._actualizar_botones()

    def _terminado(self, mensaje):
        modo = self.modo
        self.escucha = None
        self.ocupado = False
        self.barra["value"] = 0
        self.tabla.mostrar_parcial(None)
        if not self._hubo_error:
            if mensaje:
                self._estado(mensaje)
            elif modo == "vivo":
                self._estado(f"⏹ Escucha detenida.  {len(self.filas)} frase(s) en la tabla.")
            else:
                self._estado("⏹ Detenido.")
        self._actualizar_botones()

    # ---------- traduccion (hilo propio) ----------
    def _hilo_traduccion(self):
        trad = traductor.Traductor(log=lambda m: self._ui(self._aviso, m))
        reintentar = []               # (fid, texto) que aun no se pudieron traducir
        enfriar = 0.0                 # tras un fallo, no reintentar antes de esto
        aviso_google = False          # hay un aviso de "Google no responde" en pantalla
        motor_antes = None
        while not self.cerrada:
            try:
                items = [self.q_trad.get(timeout=0.5)]
            except queue.Empty:
                # nada nuevo: reintentar lo pendiente cuando toque
                if not (reintentar and time.monotonic() >= enfriar
                        and trad.puede_traducir(self.motor)):
                    continue
                items = []
            while True:                   # juntar lo acumulado: se traduce en lote
                try:
                    items.append(self.q_trad.get_nowait())
                except queue.Empty:
                    break
            motor = self.motor
            if motor != motor_antes:      # cambio de motor: reintentar ya
                motor_antes, enfriar = motor, 0.0

            if motor == "local" and any(x[0] == "preparar" for x in items):
                try:
                    trad.local()
                    self._ui(self._aviso, "✔ Traductor local listo (funciona sin internet).")
                except Exception as e:
                    enfriar = time.monotonic() + 30
                    self._ui(self._aviso, f"✗ No se pudo preparar el traductor local: {e}",
                             True)

            finales = [(fid, t) for fid, t in reintentar if fid in self.filas]
            finales += [(x[1], x[2]) for x in items if x[0] == "final"]
            reintentar = []
            if finales and (time.monotonic() < enfriar or not trad.puede_traducir(motor)):
                reintentar, finales = finales, []          # todavia no: esperar
            for i in range(0, len(finales), 40):
                lote = finales[i:i + 40]
                try:
                    res = trad.traducir([t for _, t in lote], motor)
                except Exception as e:
                    reintentar.extend(lote)
                    enfriar = time.monotonic() + 30
                    aviso_google = motor == "google"
                    self._ui(self._aviso, f"✗ {e}", True)
                    for fid, _ in lote:
                        self._ui(self._poner_es, fid, "(sin traducir todavia: se reintentara)",
                                 True)
                    continue
                if motor == "google":
                    if trad.ultimo != "google":
                        aviso_google = True
                    elif aviso_google:    # Google volvio a responder
                        aviso_google = False
                        self._ui(self._aviso, "")
                for (fid, _), es in zip(lote, res):
                    self._ui(self._poner_es, fid, es, False)

            # vista previa: solo con el traductor local (rapido y sin limites),
            # para no gastar el cupo de Google en frases a medias
            parciales = [x for x in items if x[0] == "parcial"]
            if (parciales and parciales[-1][1] == self._gen_final
                    and trad.local_listo()):
                _, gen, texto = parciales[-1]
                try:
                    self._ui(self._poner_es_parcial, gen, trad.local().traducir([texto])[0])
                except Exception:
                    pass

    def _poner_es(self, fid, texto, error):
        fila = self.filas.get(fid)
        if fila is None:                  # se limpio la tabla mientras tanto
            return
        fila["es"] = None if error else texto
        self.tabla.poner_es(fid, texto, error)

    def _poner_es_parcial(self, gen, texto):
        if gen == self._gen_final:        # sigue siendo la misma frase en curso
            self._es_parcial = texto
            self.tabla.poner_es_parcial(texto)

    def _motor_cambiado(self, _=None):
        self.motor = dict(traductor.MOTORES)[self.cbo_motor.get()]
        self._guardar_prefs()
        self._aviso("")
        if self.motor == "local":
            if traductor.falta_modelo_local():
                self._aviso("Preparando el traductor local (se descarga ~90 MB, "
                            "solo la primera vez)…")
            self.q_trad.put(("preparar",))
        # las frases que quedaron sin traducir se reintentan con el motor nuevo
        for fid, f in self.filas.items():
            if f["es"] is None:
                self.q_trad.put(("final", fid, f["en"]))

    # ---------- traducir un archivo ----------
    def _al_soltar(self, evento):
        rutas = self.root.tk.splitlist(evento.data)
        if rutas:
            self.traducir_archivo(rutas[0])

    def traducir_archivo(self, ruta=None):
        if self.ocupado:
            return
        if ruta is None:
            exts = " ".join("*" + e for e in sorted(self.extensiones))
            ruta = filedialog.askopenfilename(
                parent=self.win, title="Elige un video o audio en ingles",
                filetypes=[("Video/Audio", exts), ("Todos", "*.*")])
            if not ruta:
                return
        ruta = Path(ruta)
        if not ruta.is_file():
            messagebox.showwarning("Traducir archivo", f"No es un archivo:\n{ruta}",
                                   parent=self.win)
            return
        if self.filas and not messagebox.askyesno(
                "Traducir archivo",
                "Se borrara lo que hay ahora en la tabla. ¿Continuar?", parent=self.win):
            return
        self.limpiar(confirmar=False)
        self._archivo = ruta
        self._t_base = 0.0
        nombre = dict(CALIDADES)[self.cbo_calidad.get()]
        self._empezar("archivo")
        self._estado(f"Preparando {ruta.name}…")
        threading.Thread(target=self._trabajo_archivo, args=(nombre, ruta),
                         daemon=True).start()

    def _trabajo_archivo(self, nombre, ruta):
        mensaje = None
        try:
            modelo, device = self._obtener_modelo(nombre)
            self._evento("estado", f"Transcribiendo {ruta.name}…")
            seg_iter, info = T.abrir_transcripcion(
                modelo, ruta, idioma="en", lote=T.tam_lote(device, nombre), frases=True)
            total = getattr(info, "duration", 0) or 0
            n = 0
            for seg in seg_iter:
                if self.cancelar:
                    break
                texto = en_vivo.limpiar_texto(seg.text)
                if texto:
                    n += 1
                    self._evento("final", {"texto": texto, "ini": seg.start,
                                           "fin": seg.end})
                if total:
                    pct = min(100.0, seg.end / total * 100)
                    self._evento("progreso", pct)
                    self._evento("estado", f"Transcribiendo {ruta.name}…  {pct:.0f}%"
                                           "   (la traduccion va apareciendo al lado)")
            if self.cancelar:
                mensaje = f"⏹ Detenido: {n} frase(s) de {ruta.name}."
            else:
                mensaje = (f"✓ {ruta.name}: {n} frase(s). Guarda los subtitulos con "
                           "💬 o el texto bilingue con 💾.")
        except Exception as e:
            self._evento("error", f"No se pudo traducir el archivo: {e}")
        finally:
            self._evento("fin", mensaje)

    # ---------- copiar / guardar ----------
    def _texto(self, que, fids=None):
        """Texto para copiar/guardar: 'es', 'en' o 'ambos' (bilingue). Con
        'fids', solo esas filas; si no, todas."""
        if fids is None:
            filas = list(self.filas.values())
        else:
            filas = [self.filas[f] for f in fids if f in self.filas]
        if que == "es":
            return "\n".join(f["es"] for f in filas if f["es"])
        if que == "en":
            return "\n".join(f["en"] for f in filas)
        bloques = []
        for f in filas:
            marca = f"[{_hms(f['ini'])}] "
            bloques.append(f"{marca}{f['en']}\n{' ' * len(marca)}"
                           f"{f['es'] or '(sin traduccion)'}")
        return "\n\n".join(bloques)

    def _al_portapapeles(self, texto):
        if not texto:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(texto)
        self._estado_temporal("📋 Copiado al portapapeles.")

    def copiar(self, que):
        self._al_portapapeles(self._texto(que))
        if que == "ambos":
            self._sin_guardar = False

    def _menu_fila(self, evento, cuadro, fid, seleccion, fids):
        """Clic derecho en la tabla: copiar lo seleccionado o la frase de esa fila."""
        menu = tk.Menu(self.win, tearoff=0)
        if seleccion:
            menu.add_command(label="Copiar seleccion            Ctrl+C",
                             command=lambda: self._al_portapapeles(seleccion))
            if fids:
                n = len(fids)
                for etiqueta, que in ((f"Copiar {n} frase(s) seleccionada(s): ingles y espanol",
                                       "ambos"),
                                      (f"Copiar {n} frase(s) seleccionada(s): solo espanol",
                                       "es"),
                                      (f"Copiar {n} frase(s) seleccionada(s): solo ingles",
                                       "en")):
                    menu.add_command(label=etiqueta, command=lambda q=que: (
                        self._al_portapapeles(self._texto(q, fids))))
            menu.add_separator()
        f = self.filas.get(fid)
        if f is not None:
            menu.add_command(label="Copiar esta frase en ingles",
                             command=lambda: self._al_portapapeles(f["en"]))
            menu.add_command(label="Copiar esta frase en espanol",
                             state="normal" if f["es"] else "disabled",
                             command=lambda: self._al_portapapeles(f["es"] or ""))
            menu.add_command(label="Copiar esta frase en los dos idiomas",
                             command=lambda: self._al_portapapeles(
                                 f"{f['en']}\n{f['es'] or ''}".strip()))
            menu.add_separator()
        menu.add_command(label="Seleccionar toda la columna    Ctrl+A",
                         command=lambda: self.tabla.seleccionar_todo(cuadro))
        menu.tk_popup(evento.x_root, evento.y_root)

    def _destino_inicial(self):
        if self._archivo is not None:
            return self._archivo.parent, self._archivo.stem
        carpeta = self.carpeta_salida if self.carpeta_salida.is_dir() else Path.home()
        return carpeta, f"traduccion en vivo {datetime.now():%Y-%m-%d %H%M}"

    def _pendientes(self) -> int:
        return sum(1 for f in self.filas.values() if f["es"] is None)

    def guardar_texto(self):
        if not self.filas:
            return
        carpeta, base = self._destino_inicial()
        ruta = filedialog.asksaveasfilename(
            parent=self.win, title="Guardar transcripcion y traduccion",
            initialdir=str(carpeta), initialfile=f"{base} (traducido).txt",
            defaultextension=".txt", filetypes=[("Texto", "*.txt"), ("Todos", "*.*")])
        if not ruta:
            return
        Path(ruta).write_text(self._texto("ambos") + "\n", encoding="utf-8")
        self._sin_guardar = False
        self._estado(f"💾 Guardado en: {ruta}" + self._nota_pendientes())

    def guardar_srt(self):
        if not self.filas:
            return
        carpeta, base = self._destino_inicial()
        ruta = filedialog.asksaveasfilename(
            parent=self.win, title="Guardar subtitulos en espanol",
            initialdir=str(carpeta), initialfile=f"{base}.es.srt",
            defaultextension=".srt", filetypes=[("Subtitulos", "*.srt"), ("Todos", "*.*")])
        if not ruta:
            return
        segmentos = [{"start": f["ini"], "end": f["fin"], "text": f["es"] or f["en"]}
                     for f in self.filas.values()]
        T.escribir_srt(segmentos, Path(ruta))
        self._sin_guardar = False
        self._estado(f"💬 Subtitulos guardados en: {ruta}" + self._nota_pendientes())

    def _nota_pendientes(self) -> str:
        n = self._pendientes()
        return f"   ({n} frase(s) aun sin traducir quedaron en ingles)" if n else ""

    def limpiar(self, confirmar=True):
        if self.ocupado and self.modo == "archivo":
            return
        if confirmar and self._sin_guardar and not messagebox.askyesno(
                "Limpiar", "Hay frases sin guardar ni copiar. ¿Borrarlas?",
                parent=self.win):
            return
        self.filas.clear()
        self.tabla.limpiar()
        self._es_parcial = None
        self._sin_guardar = False
        self._archivo = None
        self._t_base = 0.0
        self._actualizar_botones()

    # ---------- cerrar ----------
    def ocupada(self) -> bool:
        return not self.cerrada and self.ocupado

    def cerrar(self):
        if self._sin_guardar and self.filas and not messagebox.askyesno(
                "Cerrar el traductor",
                "Hay frases que no has guardado ni copiado. ¿Cerrar igualmente?",
                parent=self.win):
            return
        self.apagar()
        self.win.destroy()

    def apagar(self):
        """Detiene todo sin preguntar (tambien lo usa la ventana principal al salir)."""
        self.cerrada = True
        self.cancelar = True
        if self.escucha is not None:
            self.escucha.detener()
        self._modelo_propio = None
