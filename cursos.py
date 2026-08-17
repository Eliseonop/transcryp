"""
Utilidades para organizar transcripciones por CURSO / SEMANA / SESION.

La carpeta de cursos y el catalogo se gestionan desde la interfaz (ver
app/config.py). Aqui solo viven las funciones que calculan nombres de carpeta y
la semana/sesion que corresponde a cada archivo nuevo.
"""
import re
from pathlib import Path


def limpiar_nombre(nombre: str) -> str:
    """Quita caracteres no validos para nombres de carpeta en Windows."""
    return re.sub(r'[\\/:*?"<>|]', " ", nombre).strip()


def semanas_existentes(curso_dir: Path):
    ns = []
    if curso_dir.is_dir():
        for f in curso_dir.iterdir():
            m = re.fullmatch(r"Semana (\d+)", f.name)
            if f.is_dir() and m:
                ns.append(int(m.group(1)))
    return sorted(ns)


def detectar_semana_sesion(curso_dir: Path, semana_in: str, sesion_in: str):
    """Calcula semana y sesion respetando lo que ponga el usuario; si no, auto."""
    existentes = semanas_existentes(curso_dir)

    if semana_in.isdigit():
        semana = int(semana_in)
    elif not existentes:
        semana = 1
    else:
        ultima = max(existentes)
        wk = curso_dir / f"Semana {ultima}"
        n_ses = len(list(wk.glob("sesion*.txt")))
        semana = ultima if n_ses < 2 else ultima + 1   # semana no llena -> misma; llena -> siguiente

    wk = curso_dir / f"Semana {semana}"
    if sesion_in in ("1", "2"):
        sesion = int(sesion_in)
    elif (wk / "sesion1.txt").exists() and not (wk / "sesion2.txt").exists():
        sesion = 2                                       # ya hay sesion 1 -> va a la 2
    elif not (wk / "sesion1.txt").exists():
        sesion = 1                                       # semana vacia -> sesion 1
    else:
        sesion = 2
    return semana, sesion
