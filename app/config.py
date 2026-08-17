"""
Configuracion local del transcriptor: carpeta donde se guardan los cursos y el
catalogo de cursos.

Todo se guarda en archivos JSON dentro del proyecto (config.json y cursos.json)
que NO se suben al repositorio: cada usuario tiene los suyos. Si no existen, se
crean solos la primera vez que anades una carpeta o un curso desde la interfaz.
"""
import json
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
CONFIG_JSON = RAIZ_PROYECTO / "config.json"
CATALOGO = RAIZ_PROYECTO / "cursos.json"


# ----------------------------- utilidades -----------------------------

def _leer_json(ruta: Path, por_defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return por_defecto


def _escribir_json(ruta: Path, datos) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _carpeta_cursos_por_defecto() -> Path:
    escritorio = Path.home() / "Desktop"
    base = escritorio if escritorio.is_dir() else Path.home()
    return base / "Cursos"


# ----------------------------- carpeta de cursos -----------------------------

def carpeta_cursos() -> Path:
    """Carpeta donde se guardan los cursos. Por defecto: <Escritorio>\\Cursos."""
    cfg = _leer_json(CONFIG_JSON, {})
    ruta = cfg.get("carpeta_cursos")
    return Path(ruta) if ruta else _carpeta_cursos_por_defecto()


def guardar_carpeta_cursos(ruta) -> Path:
    """Recuerda la carpeta elegida para los cursos (crea config.json si no existe)."""
    cfg = _leer_json(CONFIG_JSON, {})
    cfg["carpeta_cursos"] = str(ruta)
    _escribir_json(CONFIG_JSON, cfg)
    return Path(ruta)


# ----------------------------- catalogo de cursos -----------------------------

def cargar_cursos() -> list:
    """Lista de cursos de cursos.json. Lista vacia si no existe o esta mal."""
    datos = _leer_json(CATALOGO, [])
    return datos if isinstance(datos, list) else []


def agregar_curso(nombre: str, codigo: str = "") -> list:
    """Anade un curso al catalogo y crea cursos.json si aun no existe.

    Ignora nombres vacios y evita duplicados por nombre. Devuelve la lista final.
    """
    nombre = (nombre or "").strip()
    cursos = cargar_cursos()
    if not nombre:
        return cursos
    if any(c.get("nombre", "").strip().lower() == nombre.lower() for c in cursos):
        return cursos
    cursos.append({"nombre": nombre, "codigo": (codigo or "").strip()})
    _escribir_json(CATALOGO, cursos)
    return cursos
