"""
Escucha en vivo: captura lo que suena en el PC (un video, una clase, una
reunion…) o un microfono, detecta cuando alguien habla y lo transcribe al
momento con faster-whisper.

Funciona asi:
  1. Un hilo graba el audio a 16 kHz mono, sin pausas (para no perder nada).
  2. Otro hilo busca la voz con el detector Silero (viene con faster-whisper).
     Cuando el que habla hace una pausa, la frase se da por terminada y se
     transcribe con buena calidad ("final"). Si nadie hace pausa, se corta igual
     a los MAX_FRASE segundos, en el silencio mas largo que haya.
  3. Mientras la frase sigue, cada poco se muestra una vista previa rapida
     ("parcial"), solo si la maquina va sobrada.

No depende de la interfaz: avisa de todo llamando a on_evento(tipo, datos)
desde sus hilos (la ventana se encarga de pasarlo al hilo de Tk):
    ("escuchando", None)  la captura arranco
    ("nivel", rms)        volumen del ultimo trocito (0..1), ~10 veces por segundo
    ("parcial", texto)    vista previa de la frase en curso (None = borrarla)
    ("final", {"texto", "ini", "fin"})   frase terminada (tiempos en segundos)
    ("error", mensaje)
    ("fin", None)         se detuvo (siempre llega, al final)
"""
from __future__ import annotations

import queue
import re
import threading
import time
import warnings

import numpy as np

SR = 16000            # Whisper trabaja a 16 kHz mono
PAUSA_FIN = 0.5       # s de silencio tras la voz para dar la frase por terminada
                      # (+0,1 s del margen del detector: pausas de ~0,6 s reales)
MAX_FRASE = 12.0      # s: si nadie hace pausa, se corta igual
MIN_VOZ = 0.3         # s: menos voz que esto se ignora (clics, golpes)
COLA_SILENCIO = 0.4   # s de audio que se guarda cuando no hay voz
CADA = 0.3            # s de audio nuevo entre un analisis y el siguiente

# Contexto para la primera frase: le muestra a Whisper el estilo con puntuacion.
_PROMPT_INICIAL = "Hello, everyone. Welcome to the lesson."


# ----------------------------- utilidades -----------------------------

class _COM:
    """Inicializa COM en el hilo actual (Windows) mientras dure el 'with'.

    soundcard usa WASAPI, que necesita COM en cada hilo que graba. OJO: hay que
    importar soundcard ANTES de entrar aqui (su import tambien inicializa COM)."""

    def __enter__(self):
        self.ok = False
        try:
            import ctypes
            hr = ctypes.windll.ole32.CoInitializeEx(None, 0)   # multihilo
            self.ok = hr in (0, 1)                             # S_OK / S_FALSE
        except Exception:
            pass                                               # no es Windows
        return self

    def __exit__(self, *_):
        if self.ok:
            import ctypes
            ctypes.windll.ole32.CoUninitialize()


def _importar_soundcard():
    try:
        import soundcard as sc
    except ImportError as e:
        raise RuntimeError(
            "Falta la libreria 'soundcard'. Instalala con:  "
            r".\.venv\Scripts\pip install soundcard") from e
    # avisos de "discontinuidad" cuando el PC va cargado: no aportan nada
    warnings.filterwarnings("ignore", module="soundcard")
    warnings.filterwarnings("ignore", message=".*discontinuity.*")
    return sc


def listar_fuentes() -> list[tuple[str, dict]]:
    """Fuentes de audio disponibles: [(etiqueta, {"id", "loopback"})].

    Primero 'lo que suena en el PC' (la salida predeterminada), luego las otras
    salidas y por ultimo los microfonos (el predeterminado primero)."""
    sc = _importar_soundcard()
    fuentes = []
    with _COM():
        try:
            altavoz = sc.default_speaker()
        except Exception:
            altavoz = None
        if altavoz is not None:
            fuentes.append((f"🔊 Lo que suena en el PC  ({altavoz.name})",
                            {"id": altavoz.id, "loopback": True}))
        for s in sc.all_speakers():
            if altavoz is None or s.id != altavoz.id:
                fuentes.append((f"🔊 Lo que suena en: {s.name}",
                                {"id": s.id, "loopback": True}))
        try:
            mic_pred = sc.default_microphone().id
        except Exception:
            mic_pred = None
        mics = sorted(sc.all_microphones(), key=lambda m: m.id != mic_pred)
        for m in mics:
            extra = "  (predeterminado)" if m.id == mic_pred else ""
            fuentes.append((f"🎤 Microfono: {m.name}{extra}",
                            {"id": m.id, "loopback": False}))
    return fuentes


# Frases que Whisper "inventa" con silencio o musica de fondo.
_ALUCINACIONES = {
    "you", "thank you for watching", "thanks for watching",
    "thank you so much for watching", "please subscribe",
    "subtitles by the amaraorg community",
}


# Una misma palabra 5 o mas veces seguidas ("U-U-U-U-U", "the the the…")
_REPETICION = re.compile(r"\b(\w+)\b(?:\W+\1\b){4,}", re.IGNORECASE)


def limpiar_texto(texto: str) -> str:
    """Quita marcas como [Music] o ♪ y descarta las alucinaciones tipicas."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|[♪♫]+", " ", texto or "")
    t = " ".join(t.split())
    rep = _REPETICION.search(t)
    if rep:
        if len(t) - len(rep.group(0)) < 15:      # casi todo es repeticion: basura
            return ""
        t = _REPETICION.sub(r"\1", t)            # dejar la palabra una sola vez
    normal = " ".join(re.sub(r"[^a-z\s]", "", t.lower()).split())
    if not normal or normal in _ALUCINACIONES:
        return ""
    return t


def _mejor_corte(voz: list[dict], n: int) -> int:
    """Donde cortar una frase demasiado larga: en el silencio mas largo entre
    dos trozos de voz (pasados 3 s). Si no hay ninguno, al final."""
    mejor, hueco_max = n, -1
    for a, b in zip(voz, voz[1:]):
        if a["end"] < SR * 3:
            continue
        hueco = b["start"] - a["end"]
        if hueco > hueco_max:
            mejor, hueco_max = (a["end"] + b["start"]) // 2, hueco
    return mejor


# ----------------------------- escucha -----------------------------

class Escucha:
    """Captura + deteccion de voz + transcripcion en vivo (ver arriba)."""

    def __init__(self, modelo, fuente: dict, on_evento, idioma="en"):
        self.modelo = modelo
        self.fuente = fuente
        self.on_evento = on_evento
        self.idioma = idioma
        self._parar = threading.Event()
        self._audio = queue.Queue()
        self._contexto = ""              # lo ultimo dicho (ayuda a Whisper)
        self._hilos = []

    def iniciar(self):
        for destino in (self._capturar, self._procesar):
            h = threading.Thread(target=destino, daemon=True)
            h.start()
            self._hilos.append(h)

    def detener(self):
        """Pide parar. Lo que se estaba diciendo se transcribe y luego llega 'fin'."""
        self._parar.set()

    # ---------- hilo 1: grabar ----------
    def _capturar(self):
        try:
            sc = _importar_soundcard()
            with _COM():
                fuente = sc.get_microphone(self.fuente["id"],
                                           include_loopback=self.fuente["loopback"])
                # buffer de 0,5 s en Windows: aguanta si el PC va cargado
                with fuente.recorder(samplerate=SR, channels=1, blocksize=SR // 2) as rec:
                    self.on_evento("escuchando", None)
                    while not self._parar.is_set():
                        trozo = rec.record(numframes=SR // 10)[:, 0].astype(np.float32)
                        self._audio.put(trozo)
                        self.on_evento("nivel", float(np.sqrt(np.mean(trozo ** 2))))
        except Exception as e:
            self.on_evento("error", f"No se pudo capturar el audio: "
                                    f"{type(e).__name__}: {e}")
            self._parar.set()
        finally:
            self._audio.put(None)        # despierta al otro hilo

    # ---------- hilo 2: detectar voz y transcribir ----------
    def _juntar_audio(self, buf):
        """Espera audio nuevo (al menos CADA segundos). Devuelve (buf, se_acabo)."""
        nuevos, cuanto = [], 0
        while cuanto < SR * CADA:
            try:
                trozo = self._audio.get(timeout=0.5)
            except queue.Empty:
                if self._parar.is_set():
                    return buf, True
                continue
            if trozo is None:
                return (np.concatenate([buf, *nuevos]) if nuevos else buf), True
            nuevos.append(trozo)
            cuanto += len(trozo)
        return np.concatenate([buf, *nuevos]), self._parar.is_set()

    def _procesar(self):
        try:
            from faster_whisper.vad import VadOptions, get_speech_timestamps
            vad = VadOptions(threshold=0.5, min_silence_duration_ms=250,
                             speech_pad_ms=100)
            # "calentar" el modelo: la primera pasada en GPU es lenta
            self._transcribir(np.zeros(SR, dtype=np.float32), rapido=True)
            buf = np.zeros(0, dtype=np.float32)
            base = 0                    # muestras ya descartadas (para los tiempos)
            prox_parcial = 0.0
            hay_parcial = False
            while True:
                buf, se_acabo = self._juntar_audio(buf)
                voz = get_speech_timestamps(buf, vad, SR) if len(buf) >= SR // 2 else []

                if se_acabo:            # se pidio parar: cerrar lo que se estaba diciendo
                    if voz:
                        self._frase(buf[voz[0]["start"]:voz[-1]["end"]],
                                    base + voz[0]["start"], base + voz[-1]["end"])
                    elif hay_parcial:
                        self.on_evento("parcial", None)
                    break

                if not voz:             # silencio: guardar solo un poquito
                    if hay_parcial:
                        self.on_evento("parcial", None)
                        hay_parcial = False
                    guardar = int(SR * COLA_SILENCIO)
                    if len(buf) > guardar:
                        base += len(buf) - guardar
                        buf = buf[-guardar:]
                    continue

                fin_voz = voz[-1]["end"]
                corte = None
                if len(buf) - fin_voz >= SR * PAUSA_FIN:     # hizo una pausa
                    corte = fin_voz
                elif len(buf) >= SR * MAX_FRASE:              # habla sin parar
                    corte = _mejor_corte(voz, len(buf))

                if corte is not None:
                    ini = voz[0]["start"]
                    hablado = sum(min(v["end"], corte) - v["start"]
                                  for v in voz if v["start"] < corte)
                    if hablado >= SR * MIN_VOZ:
                        self._frase(buf[ini:corte], base + ini, base + corte)
                    elif hay_parcial:
                        self.on_evento("parcial", None)
                    hay_parcial = False
                    base += corte
                    buf = buf[corte:]
                    continue

                # la frase sigue: vista previa rapida si la maquina da para ello
                ahora = time.monotonic()
                if ahora >= prox_parcial and len(buf) - voz[0]["start"] >= SR:
                    texto = self._transcribir(buf[voz[0]["start"]:], rapido=True)
                    coste = time.monotonic() - ahora
                    # si tarda mucho (CPU lenta) se espacian para no ir con retraso
                    prox_parcial = time.monotonic() + max(1.0, 2.5 * coste)
                    if texto:
                        self.on_evento("parcial", texto)
                        hay_parcial = True
        except Exception as e:
            self.on_evento("error", f"Error al transcribir: {type(e).__name__}: {e}")
        finally:
            self._parar.set()
            self.on_evento("fin", None)

    def _frase(self, audio, ini, fin):
        texto = self._transcribir(audio, rapido=False)
        if texto:
            self._contexto = (self._contexto + " " + texto)[-200:]
            self.on_evento("final", {"texto": texto, "ini": ini / SR, "fin": fin / SR})
        else:
            self.on_evento("parcial", None)

    def _transcribir(self, audio, rapido: bool) -> str:
        if rapido:
            # vista previa: lo mas rapido posible y SIN contexto (con contexto,
            # Whisper tiende a "completar" la frase a medias con lo anterior)
            opciones = dict(beam_size=1, temperature=0.0, without_timestamps=True)
        else:
            # frase final: con marcas de tiempo (sin ellas, la busqueda beam a
            # veces devuelve todo en minusculas y sin puntuacion) y con lo
            # ultimo dicho como contexto, que ademas mantiene el estilo puntuado
            opciones = dict(beam_size=5, temperature=[0.0, 0.2, 0.4],
                            initial_prompt=self._contexto.strip() or _PROMPT_INICIAL)
        segmentos, _ = self.modelo.transcribe(
            audio, language=self.idioma, vad_filter=False,
            condition_on_previous_text=False,
            # tope de palabras segun lo que dura el audio: si Whisper entra en
            # bucle ("of the new product of the new product…") no se eterniza
            max_new_tokens=int(10 + 7 * len(audio) / SR), **opciones)
        # compresion alta = texto repetido en bucle: se descarta
        return limpiar_texto(" ".join(s.text.strip() for s in segmentos
                                      if s.compression_ratio <= 2.4))
