# Transcryp — Transcriptor local (offline)

Transcribe cualquier **video o audio** (mp4, mkv, mov, wav, mp3, m4a, flac…) a
texto. Funciona **100 % en tu computadora**, sin cuentas ni tokens, y aprovecha
tu **GPU NVIDIA** si la tienes.

- Motor de voz: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (modelo Whisper).
- Separar hablantes: [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx).

---

## Instalar (desde cero)

Necesitas **Python 3.10+** y **ffmpeg**.

```powershell
# 1. Clonar
git clone https://github.com/Eliseonop/transcryp.git
cd transcryp

# 2. Crear entorno e instalar dependencias
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 3. ffmpeg (si no lo tienes)
winget install ffmpeg
```

> Si **no** tienes GPU NVIDIA, comenta las líneas `nvidia-*` de `requirements.txt`
> antes de instalar: el programa usará la CPU automáticamente.

## Usar

```powershell
.\.venv\Scripts\python main.py
```

Se abre la ventana: arrastra un video/audio, elige idioma y pulsa **Transcribir**.

### Guardar organizado por curso (opcional)

Marca **Guardar organizado por curso**, elige la **carpeta** donde se guardan y
añade cursos con **➕ Curso**. Tus cursos quedan en un `cursos.json` local (no se
sube al repositorio; usa [`cursos.example.json`](cursos.example.json) como
referencia). Cada transcripción se guarda en `…\<Curso>\Semana N\sesionM.txt`.

### Modelos que se descargan solos

Nada pesado viaja en el repositorio. Se descarga automáticamente la primera vez:

| Qué | Cuándo | Dónde queda |
|-----|--------|-------------|
| Modelo Whisper (~3 GB) | 1ª transcripción | caché de HuggingFace |
| Modelos de hablantes (~34 MB) | al usar **Separar quien habla**, o con el botón **🔧 Verificar / Preparar** | carpeta `modelos/` |

El botón **🔧 Verificar / Preparar** de la ventana comprueba qué falta y lo descarga.
También puedes prepararlo desde la terminal:

```powershell
.\.venv\Scripts\python -m app.setup_modelos
```

## Línea de comandos

```powershell
.\.venv\Scripts\python transcribir.py "video.mp4" --idioma es --diarizar
```

Más opciones y detalles en [LEEME.md](LEEME.md).
