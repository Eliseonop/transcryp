"""
Verificacion y descarga de los modelos de diarizacion (separar hablantes).

Estos modelos NO se suben al repositorio (pesan ~34 MB). La primera vez que
haces falta separar hablantes, se descargan automaticamente desde los releases
oficiales de sherpa-onnx y quedan guardados en la carpeta 'modelos/'.

Modelos que se necesitan:
  - modelos/embedding.onnx
      -> 3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx  (~27 MB)
  - modelos/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
      -> sherpa-onnx-pyannote-segmentation-3-0.tar.bz2         (~7 MB)

No requiere ninguna libreria extra: usa solo la libreria estandar de Python.
El modelo grande de voz (Whisper large-v3, ~3 GB) NO se maneja aqui: lo descarga
faster-whisper por su cuenta la primera vez que transcribes.
"""
from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Carpeta 'modelos' en la raiz del proyecto (este archivo esta en app/).
MODELOS_DIR = Path(__file__).resolve().parent.parent / "modelos"

# Rutas finales que el resto del programa espera encontrar.
EMBEDDING = MODELOS_DIR / "embedding.onnx"
SEGMENTACION = MODELOS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"

# URLs oficiales (releases publicos y permanentes de sherpa-onnx).
URL_EMBEDDING = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
)
URL_SEG_TAR = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/"
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)


def faltan_modelos() -> bool:
    """True si falta alguno de los modelos de diarizacion."""
    return not (EMBEDDING.is_file() and SEGMENTACION.is_file())


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _descargar(url: str, destino: Path, log) -> None:
    """Descarga 'url' a 'destino' de forma atomica, informando el progreso."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    log(f"Descargando {destino.name}…")
    tmp = destino.with_suffix(destino.suffix + ".parte")
    req = urllib.request.Request(url, headers={"User-Agent": "transcryp-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        leido = 0
        while True:
            trozo = r.read(1024 * 256)
            if not trozo:
                break
            f.write(trozo)
            leido += len(trozo)
            if total:
                log(f"  {destino.name}: {_mb(leido)} / {_mb(total)} "
                    f"({leido * 100 // total}%)")
    tmp.replace(destino)
    log(f"✔ {destino.name} listo ({_mb(destino.stat().st_size)}).")


def verificar_y_descargar(log=print) -> bool:
    """Descarga lo que falte. Devuelve True si al final esta todo listo.

    'log' es una funcion que recibe mensajes de texto (por defecto print);
    la interfaz grafica le pasa una que escribe en pantalla.
    """
    if not faltan_modelos():
        log("✔ Todos los modelos de hablantes ya estan descargados.")
        return True

    MODELOS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Embedding (huella de voz)
    if not EMBEDDING.is_file():
        _descargar(URL_EMBEDDING, EMBEDDING, log)

    # 2) Segmentacion (viene en un .tar.bz2 que hay que extraer)
    if not SEGMENTACION.is_file():
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = Path(tmpdir) / "seg.tar.bz2"
            _descargar(URL_SEG_TAR, tar_path, log)
            log("Extrayendo modelo de segmentacion…")
            with tarfile.open(tar_path, "r:bz2") as tar:
                tar.extractall(MODELOS_DIR)
        if SEGMENTACION.is_file():
            log("✔ Segmentacion lista.")

    ok = not faltan_modelos()
    log("✔ Preparacion completa." if ok
        else "✗ No se pudo dejar todo listo. Revisa tu conexion e intenta de nuevo.")
    return ok


if __name__ == "__main__":
    # Permite prepararlo tambien desde la terminal:  python -m app.setup_modelos
    verificar_y_descargar()
