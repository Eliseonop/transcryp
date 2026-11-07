"""
Utilidades para guardar transcripciones por CURSO.

Cada curso es una sola carpeta y dentro van solo los .txt de las
transcripciones, con el nombre del video/audio original:

    <carpeta de cursos>\\<Curso>\\<nombre del video>.txt

La carpeta de cursos y el catalogo se gestionan desde la interfaz (ver
app/config.py).
"""
import re
from pathlib import Path


def limpiar_nombre(nombre: str) -> str:
    """Quita caracteres no validos para nombres de carpeta en Windows."""
    return re.sub(r'[\\/:*?"<>|]', " ", nombre).strip()


def transcripciones_existentes(curso_dir: Path) -> int:
    """Cuantos .txt hay ya guardados en la carpeta del curso."""
    if not curso_dir.is_dir():
        return 0
    return sum(1 for f in curso_dir.glob("*.txt") if f.is_file())


def ruta_txt_libre(curso_dir: Path, nombre: str) -> Path:
    """Ruta <curso_dir>/<nombre>.txt que no pise otra transcripcion.

    Si ya existe, prueba 'nombre (2).txt', 'nombre (3).txt', etc."""
    base = limpiar_nombre(nombre) or "transcripcion"
    destino = curso_dir / f"{base}.txt"
    n = 2
    while destino.exists():
        destino = curso_dir / f"{base} ({n}).txt"
        n += 1
    return destino
