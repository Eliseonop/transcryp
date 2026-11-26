"""
Traduccion de frases de ingles a espanol, gratis y sin cuentas.

Dos motores a elegir:
  - "local":  modelo Argos Translate (entrenado con OPUS) que corre con
    CTranslate2, la misma libreria que usa faster-whisper. Funciona 100 % en tu
    PC, sin limites. Se descarga solo la primera vez (~90 MB) en
    modelos/traduccion/en_es/.
  - "google": Google Translate (el servicio gratuito, sin clave). Necesita
    internet y suena algo mas natural, pero tiene un LIMITE de uso: si se
    hacen muchas peticiones seguidas responde "429 Too Many Requests".

Si Google falla (sin internet, limite de uso…) se deja en pausa un rato (1 min,
luego mas) y mientras tanto se usa el traductor local si esta descargado.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from app.setup_modelos import MODELOS_DIR, _descargar

# Motores ofrecidos en la interfaz: etiqueta -> clave
MOTORES = [
    ("Local (sin internet, sin limites)", "local"),
    ("Google (en linea, con limite de uso)", "google"),
]

DIR_LOCAL = MODELOS_DIR / "traduccion" / "en_es"
URL_LOCAL = "https://argos-net.com/v1/translate-en_es-1_0.argosmodel"

URL_GOOGLE = "https://translate.googleapis.com/translate_a/single"
_MAX_CARACTERES = 4500           # por peticion a Google (varias frases juntas)
_ESPACIO_GOOGLE = 1.0            # s minimos entre dos peticiones a Google
_ultima_peticion = 0.0


class ErrorTraduccion(Exception):
    """No se pudo traducir con ningun motor disponible."""


# ----------------------------- Google (en linea) -----------------------------

def _google_peticion(texto: str) -> str:
    global _ultima_peticion
    espera = _ultima_peticion + _ESPACIO_GOOGLE - time.monotonic()
    if espera > 0:                   # no bombardear el servicio gratuito
        time.sleep(espera)
    _ultima_peticion = time.monotonic()
    params = urllib.parse.urlencode(
        {"client": "gtx", "sl": "en", "tl": "es", "dt": "t"})
    datos = urllib.parse.urlencode({"q": texto}).encode("utf-8")
    req = urllib.request.Request(
        f"{URL_GOOGLE}?{params}", data=datos,
        headers={"User-Agent": "transcryp",
                 "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        respuesta = json.loads(r.read().decode("utf-8"))
    return "".join(p[0] for p in (respuesta[0] or []) if p and p[0])


def traducir_google(textos: list[str]) -> list[str]:
    """Traduce una lista de frases. Junta varias en cada peticion (una por
    linea) para ir rapido con archivos largos sin saturar el servicio."""
    salida = [""] * len(textos)
    pendientes = [(i, " ".join(t.split())) for i, t in enumerate(textos) if t.strip()]
    bloques, bloque, largo = [], [], 0
    for i, t in pendientes:
        if bloque and largo + len(t) + 1 > _MAX_CARACTERES:
            bloques.append(bloque)
            bloque, largo = [], 0
        bloque.append((i, t))
        largo += len(t) + 1
    if bloque:
        bloques.append(bloque)

    for bloque in bloques:
        partes = _google_peticion("\n".join(t for _, t in bloque)).split("\n")
        if len(partes) != len(bloque):   # no respeto las lineas: de una en una
            partes = [_google_peticion(t) for _, t in bloque]
        for (i, _), trad in zip(bloque, partes):
            salida[i] = trad.strip()
    return salida


# ----------------------------- local (sin internet) -----------------------------

def falta_modelo_local() -> bool:
    return not ((DIR_LOCAL / "model" / "model.bin").is_file()
                and (DIR_LOCAL / "sentencepiece.model").is_file())


def descargar_modelo_local(log=print) -> None:
    """Descarga y extrae el modelo de traduccion local si aun no esta."""
    if not falta_modelo_local():
        return
    temporal = DIR_LOCAL.with_name(DIR_LOCAL.name + ".parte")
    with tempfile.TemporaryDirectory() as tmp:
        paquete = Path(tmp) / "en_es.argosmodel"
        _descargar(URL_LOCAL, paquete, log)
        log("Extrayendo el modelo de traduccion…")
        shutil.rmtree(temporal, ignore_errors=True)
        with zipfile.ZipFile(paquete) as z:
            for info in z.infolist():
                partes = Path(info.filename).parts       # ('en_es', 'model', ...)
                if info.is_dir() or len(partes) < 2 or ".." in partes:
                    continue
                rel = Path(*partes[1:])
                # solo hace falta el modelo y el tokenizador (no 'stanza/')
                if rel.parts[0] != "model" and rel.name != "sentencepiece.model":
                    continue
                destino = temporal / rel
                destino.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as origen, open(destino, "wb") as f:
                    shutil.copyfileobj(origen, f)
    shutil.rmtree(DIR_LOCAL, ignore_errors=True)
    temporal.replace(DIR_LOCAL)
    log("✔ Modelo de traduccion listo.")


# Fin de frase: . ! ? seguido de espacio y mayuscula (sin cortar "Mr. Smith").
_FIN_FRASE = re.compile(
    r"(?<=[.!?…])(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bSt\.)"
    r"(?<!\bvs\.)\s+(?=[\"'(¿¡]?[A-Z0-9])")


class TraductorLocal:
    """Modelo OPUS en->es de Argos, ejecutado con CTranslate2 en la CPU (va
    rapido y no le quita memoria de la GPU a Whisper)."""

    def __init__(self):
        import ctranslate2
        import sentencepiece
        self.sp = sentencepiece.SentencePieceProcessor(
            model_file=str(DIR_LOCAL / "sentencepiece.model"))
        self.modelo = ctranslate2.Translator(
            str(DIR_LOCAL / "model"), device="cpu", compute_type="int8",
            intra_threads=max(1, min(4, os.cpu_count() or 1)))

    def traducir(self, textos: list[str]) -> list[str]:
        # El modelo se entreno frase a frase: se parte cada texto en frases,
        # se traducen todas de una vez y se vuelven a juntar.
        frases, dueno = [], []
        for i, t in enumerate(textos):
            for f in _FIN_FRASE.split(" ".join(t.split())):
                if f.strip():
                    frases.append(f)
                    dueno.append(i)
        if not frases:
            return [""] * len(textos)
        tokens = [self.sp.encode(f, out_type=str) for f in frases]
        res = self.modelo.translate_batch(
            tokens, beam_size=4, max_batch_size=32, max_decoding_length=256)
        partes = [[] for _ in textos]
        for i, r in zip(dueno, res):
            partes[i].append(self.sp.decode(r.hypotheses[0]))
        return [" ".join(p).strip() for p in partes]


# ----------------------------- traductor con respaldo -----------------------------

def _motivo(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError) and error.code == 429:
        return "limite de uso del servicio gratuito"
    if isinstance(error, urllib.error.URLError):
        return "sin conexion"
    return str(error)


class Traductor:
    """Traduce con el motor elegido ("local" o "google").

    Si Google falla, queda en pausa un rato (1 min, y el doble cada vez que
    vuelve a fallar, hasta 10 min) y mientras tanto se usa el local si esta
    descargado. Pensado para usarse siempre desde el MISMO hilo de trabajo."""

    def __init__(self, log=print):
        self.log = log
        self._local = None
        self.ultimo = None           # motor que se uso en la ultima traduccion
        self._pausa_google = 0.0     # hasta cuando no se llama a Google
        self._castigo = 60.0         # duracion de la proxima pausa

    def local(self) -> TraductorLocal:
        """El traductor local (lo descarga y carga la primera vez)."""
        if self._local is None:
            if falta_modelo_local():
                descargar_modelo_local(self.log)
            self._local = TraductorLocal()
        return self._local

    def local_listo(self) -> bool:
        """True si el traductor local se puede usar sin descargar nada."""
        return self._local is not None or not falta_modelo_local()

    def puede_traducir(self, motor: str) -> bool:
        """False solo si Google esta en pausa y no hay local de respaldo."""
        return (motor == "local" or time.monotonic() >= self._pausa_google
                or self.local_listo())

    def traducir(self, textos: list[str], motor: str) -> list[str]:
        if motor == "google":
            espera = self._pausa_google - time.monotonic()
            if espera <= 0:
                try:
                    res = traducir_google(textos)
                    self.ultimo = "google"
                    self._castigo = 60.0
                    return res
                except Exception as e:
                    motivo = _motivo(e)
                    espera = self._castigo
                    self._pausa_google = time.monotonic() + espera
                    self._castigo = min(self._castigo * 2, 600.0)
            else:
                motivo = "en pausa"
            if not self.local_listo():
                raise ErrorTraduccion(
                    f"Google no responde ({motivo}): se reintenta en {int(espera)} s. "
                    "Elige 'Local (sin internet)' para no depender de Google.")
            self.log(f"Google no responde ({motivo}): se usa el traductor local "
                     f"y se vuelve a probar Google en {int(espera)} s.")
        res = self.local().traducir(textos)
        self.ultimo = "local"
        return res
