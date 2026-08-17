"""
Punto de entrada del Transcriptor.

Abre la interfaz grafica (arrastra un video/audio, elige idioma y transcribe).

    python main.py

Tambien puedes usar la version de linea de comandos:  python transcribir.py "archivo.mp4"
"""
import subprocess
import sys
from pathlib import Path


def _asegurar_venv():
    """Si nos abren con otro Python (PyCharm, doble clic, python del sistema),
    relanza la app con el Python del .venv, que tiene las librerias instaladas.
    Asi 'No module named faster_whisper' no vuelve a aparecer."""
    raiz = Path(__file__).resolve().parent
    scripts = raiz / ".venv" / "Scripts"
    venv_py = scripts / "pythonw.exe"
    if not venv_py.is_file():
        return  # no hay entorno; seguimos con el Python actual
    actual = Path(sys.executable).resolve()
    if actual.parent == scripts.resolve():
        return  # ya estamos dentro del .venv, todo bien
    try:
        subprocess.Popen([str(venv_py), str(raiz / "main.py")])
    except Exception:
        return  # si el relanzamiento falla, intentamos seguir igual
    sys.exit(0)


def main():
    _asegurar_venv()
    from app.gui import lanzar
    lanzar()


if __name__ == "__main__":
    main()
