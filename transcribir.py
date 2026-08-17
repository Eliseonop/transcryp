"""
Transcriptor local de audio/video (mp4, wav, mp3, mkv, m4a, etc.)
Usa faster-whisper. Funciona 100% offline. Aprovecha la GPU si esta disponible.

Uso basico:
    python transcribir.py "ruta\\del\\archivo.mp4"

Una carpeta entera (lote):
    python transcribir.py "C:\\mis videos"

Con quien habla (diarizacion) y marcas por palabra:
    python transcribir.py "reunion.mp4" --diarizar --palabras

Opciones:
    --idioma es            fuerza el idioma (mas rapido y preciso)
    --modelo large-v3      tiny|base|small|medium|large-v3 (def: large-v3)
    --formatos txt srt     salidas: txt srt vtt json  (def: txt srt)
    --dispositivo auto     auto|cuda|cpu
    --diarizar             separa e identifica hablantes (Hablante 1, 2...)
    --hablantes 2          nº de hablantes si lo sabes (def: automatico)
    --palabras             marca de tiempo por cada palabra (guarda .json)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

MEDIA = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v",
         ".mpg", ".mpeg", ".ts", ".wav", ".mp3", ".m4a", ".flac", ".ogg",
         ".opus", ".aac", ".wma", ".aiff", ".alac"}


def _cargar_dlls_cuda():
    """En Windows anade las carpetas bin de cuBLAS/cuDNN (instaladas via pip)
    al buscador de DLLs y al PATH para que CTranslate2 encuentre CUDA."""
    if os.name != "nt":
        return
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn", "cuda_nvrtc"):
        binp = base / sub / "bin"
        if binp.is_dir():
            try:
                os.add_dll_directory(str(binp))
            except Exception:
                pass
            os.environ["PATH"] = str(binp) + os.pathsep + os.environ.get("PATH", "")


def formato_tiempo(segundos: float, sep: str = ",") -> str:
    ms = int(round(segundos * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


# ----------------------------- escritura de salidas -----------------------------

def _prefijo(seg) -> str:
    return f"[{seg['speaker']}] " if seg.get("speaker") else ""


def escribir_txt(segmentos, destino: Path):
    with open(destino, "w", encoding="utf-8") as f:
        actual = object()
        for seg in segmentos:
            hablante = seg.get("speaker")
            if hablante and hablante != actual:      # linea en blanco al cambiar de hablante
                if actual is not object():
                    f.write("\n")
                f.write(f"{hablante}:\n")
                actual = hablante
            f.write(seg["text"].strip() + "\n")


def escribir_srt(segmentos, destino: Path):
    with open(destino, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segmentos, 1):
            f.write(f"{i}\n")
            f.write(f"{formato_tiempo(seg['start'])} --> {formato_tiempo(seg['end'])}\n")
            f.write(_prefijo(seg) + seg["text"].strip() + "\n\n")


def escribir_vtt(segmentos, destino: Path):
    with open(destino, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segmentos:
            ini = formato_tiempo(seg["start"], ".")
            fin = formato_tiempo(seg["end"], ".")
            f.write(f"{ini} --> {fin}\n")
            f.write(_prefijo(seg) + seg["text"].strip() + "\n\n")


def escribir_json(segmentos, destino: Path):
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(segmentos, f, ensure_ascii=False, indent=2)


ESCRITORES = {"txt": escribir_txt, "srt": escribir_srt,
              "vtt": escribir_vtt, "json": escribir_json}


# ----------------------------- diarizacion (quien habla) -----------------------------

def cargar_diarizador(n_hablantes: int):
    import sherpa_onnx
    base = Path(__file__).parent / "modelos"
    seg = base / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
    emb = base / "embedding.onnx"
    if not seg.is_file() or not emb.is_file():
        raise FileNotFoundError(
            "Faltan los modelos de diarizacion en la carpeta 'modelos'. "
            "Descarga segmentacion y embedding (ver LEEME.md).")
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg))),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb)),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=(n_hablantes if n_hablantes and n_hablantes > 0 else -1),
            threshold=0.5),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    return sherpa_onnx.OfflineSpeakerDiarization(cfg)


def diarizar(sd, ruta: Path):
    from faster_whisper.audio import decode_audio
    samples = decode_audio(str(ruta), sampling_rate=sd.sample_rate)
    res = sd.process(samples).sort_by_start_time()
    return [{"start": s.start, "end": s.end, "speaker": s.speaker} for s in res]


def hablante_de(inicio, fin, diar_segs):
    """Devuelve el hablante que mas se solapa con [inicio, fin]."""
    mejor, mejor_ov = None, 0.0
    centro = (inicio + fin) / 2
    for d in diar_segs:
        ov = min(fin, d["end"]) - max(inicio, d["start"])
        if ov > mejor_ov:
            mejor_ov, mejor = ov, d["speaker"]
    if mejor is None:                       # sin solape: el mas cercano al centro
        mejor = min(diar_segs,
                    key=lambda d: abs(((d["start"] + d["end"]) / 2) - centro),
                    default={"speaker": 0})["speaker"]
    return f"Hablante {mejor + 1}"


# ----------------------------- carga del modelo -----------------------------

def cargar_modelo(nombre="large-v3", dispositivo="auto"):
    """Carga WhisperModel eligiendo GPU/CPU. Devuelve (modelo, device, compute)."""
    _cargar_dlls_cuda()
    from faster_whisper import WhisperModel
    device = dispositivo
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"
    print(f"[i] Modelo: {nombre} | Dispositivo: {device} ({compute})")
    print("[i] Cargando modelo (la 1a vez descarga ~1-3 GB)...")
    try:
        modelo = WhisperModel(nombre, device=device, compute_type=compute)
    except Exception as e:
        if device == "cuda":
            print(f"[!] Fallo la GPU ({e}). Reintentando en CPU...")
            device, compute = "cpu", "int8"
            modelo = WhisperModel(nombre, device="cpu", compute_type="int8")
        else:
            raise
    return modelo, device, compute


# ----------------------------- transcripcion de un archivo -----------------------------

def mmss(segundos: float) -> str:
    """Formatea una duracion como 'X min Y s'."""
    s = int(round(segundos))
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def obtener_segmentos(modelo, entrada: Path, idioma=None, palabras=False, sd=None):
    """Transcribe (y opcionalmente diariza) un archivo. Devuelve lista de segmentos."""
    print(f"\n[i] Archivo: {entrada.name}")
    print("[i] Transcribiendo...")
    t0 = time.time()
    con_palabras = palabras or (sd is not None)
    seg_iter, info = modelo.transcribe(
        str(entrada), language=idioma, vad_filter=True,
        beam_size=5, word_timestamps=con_palabras)
    total = getattr(info, "duration", 0) or 0
    dur_txt = formato_tiempo(total).split(",")[0]
    print(f"[i] Idioma: {info.language} (prob {info.language_probability:.2f}) "
          f"| Duracion del audio: {dur_txt}")

    segmentos = []
    for seg in seg_iter:
        pal = None
        if con_palabras and seg.words:
            pal = [{"start": round(w.start, 3), "end": round(w.end, 3),
                    "word": w.word} for w in seg.words]
        segmentos.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                          "text": seg.text.strip(), "words": pal})
        transcurrido = int(time.time() - t0)
        pct = f"{min(100, seg.end / total * 100):5.1f}%" if total else "     "
        print(f"  [{transcurrido:4d}s] {pct} {seg.text.strip()}")

    fases = {"transcripcion": time.time() - t0, "diarizacion": None}

    if sd is not None:
        print("[i] Identificando hablantes (diarizacion)...")
        td = time.time()
        diar = diarizar(sd, entrada)
        n = len({d["speaker"] for d in diar}) if diar else 0
        print(f"[i] Hablantes detectados: {n}")
        for seg in segmentos:
            seg["speaker"] = hablante_de(seg["start"], seg["end"], diar) if diar else None
        fases["diarizacion"] = time.time() - td
    return segmentos, fases


def guardar(segmentos, destino_base: Path, formatos):
    """Escribe los formatos pedidos usando destino_base (sin extension)."""
    for fmt in formatos:
        destino = destino_base.with_suffix("." + fmt)
        ESCRITORES[fmt](segmentos, destino)
        print(f"    -> {destino.name}")


def imprimir_fases(fases):
    print(f"[i] Primera fase (transcripcion): demoro {mmss(fases['transcripcion'])}")
    if fases["diarizacion"] is not None:
        print(f"[i] Segunda fase (hablantes): demoro {mmss(fases['diarizacion'])}")


def transcribir_archivo(modelo, entrada: Path, args, sd=None):
    segmentos, fases = obtener_segmentos(modelo, entrada, args.idioma, args.palabras, sd)
    imprimir_fases(fases)
    print("[i] Guardando...")
    guardar(segmentos, entrada, args.formatos)


# ----------------------------- main -----------------------------

def main():
    p = argparse.ArgumentParser(description="Transcriptor local (faster-whisper)")
    p.add_argument("archivo", help="Archivo o CARPETA de audio/video a transcribir")
    p.add_argument("--modelo", default="large-v3")
    p.add_argument("--idioma", default=None)
    p.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--formatos", nargs="+", default=["txt", "srt"],
                   choices=["txt", "srt", "vtt", "json"])
    p.add_argument("--diarizar", action="store_true",
                   help="Separa e identifica hablantes")
    p.add_argument("--hablantes", type=int, default=0,
                   help="Nº de hablantes si lo sabes (def: automatico)")
    p.add_argument("--palabras", action="store_true",
                   help="Marca de tiempo por palabra (guarda .json)")
    args = p.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    if args.palabras and "json" not in args.formatos:
        args.formatos = list(args.formatos) + ["json"]

    ruta = Path(args.archivo).expanduser().resolve()
    if ruta.is_dir():
        archivos = sorted(f for f in ruta.iterdir()
                          if f.is_file() and f.suffix.lower() in MEDIA)
        if not archivos:
            print(f"[X] No hay archivos de audio/video en: {ruta}")
            sys.exit(1)
        print(f"[i] Lote: {len(archivos)} archivo(s) en {ruta}")
    elif ruta.is_file():
        archivos = [ruta]
    else:
        print(f"[X] No existe: {ruta}")
        sys.exit(1)

    modelo, device, compute = cargar_modelo(args.modelo, args.dispositivo)

    sd = None
    if args.diarizar:
        print("[i] Cargando diarizador (quien habla)...")
        sd = cargar_diarizador(args.hablantes)

    for f in archivos:
        try:
            transcribir_archivo(modelo, f, args, sd)
        except Exception as e:
            print(f"[X] Error con {f.name}: {e}")

    print("\n[OK] Transcripcion completada.")


if __name__ == "__main__":
    main()
