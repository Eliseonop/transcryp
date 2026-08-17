# Transcriptor local (offline)

Transcribe cualquier video o audio (**mp4, mkv, mov, avi, wav, mp3, m4a, flac, ogg...**)
a texto. Funciona **100% en tu computadora, sin internet**, y usa tu **GPU RTX 4060**
para ir rápido.

Motor: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (modelo Whisper de OpenAI)
+ [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) para separar hablantes.

---

## Forma fácil (la aplicación)

```powershell
.\.venv\Scripts\python.exe main.py
```

Se abre la ventana: **arrastra** el video/audio, elige idioma/calidad y pulsa
**Transcribir**. Opciones útiles dentro de la app:

- **Separar quien habla** → identifica Hablante 1, 2…
- **Guardar organizado por curso** → elige la **carpeta** donde se guardan los
  cursos y añade cursos con **➕ Curso** (se guardan en tu `cursos.json` local).
  Cada transcripción queda en `…\<Curso>\Semana N\sesionM.txt` (+ `.srt`).

## Forma por línea de comandos

Abre PowerShell en esta carpeta y ejecuta:

```powershell
.\.venv\Scripts\python.exe transcribir.py "C:\ruta\a\mi_video.mp4"
```

### Un solo archivo o una CARPETA entera (lote)

```powershell
# un archivo
.\.venv\Scripts\python.exe transcribir.py "video.mp4"

# todos los audios/videos de una carpeta
.\.venv\Scripts\python.exe transcribir.py "C:\mis grabaciones"
```

### Opciones

| Opción          | Qué hace                                          | Ejemplo                  |
|-----------------|---------------------------------------------------|--------------------------|
| `--idioma`      | Fuerza el idioma (más rápido y preciso)           | `--idioma es`            |
| `--modelo`      | Calidad vs velocidad                              | `--modelo medium`        |
| `--formatos`    | Salidas: `txt srt vtt json`                       | `--formatos txt srt vtt` |
| `--diarizar`    | Separa e identifica hablantes (Hablante 1, 2...)  | `--diarizar`             |
| `--hablantes`   | Nº de hablantes si lo sabes (si no, automático)   | `--hablantes 2`          |
| `--palabras`    | Marca de tiempo por cada palabra (guarda `.json`) | `--palabras`             |
| `--dispositivo` | `auto`, `cuda` (GPU) o `cpu`                       | `--dispositivo cpu`      |

Ejemplo con todo:

```powershell
.\.venv\Scripts\python.exe transcribir.py "reunion.mp4" --idioma es --diarizar --palabras --formatos txt srt json
```

### Formatos de salida

- **`.txt`** — texto plano (con `Hablante N:` si usas `--diarizar`).
- **`.srt`** / **`.vtt`** — subtítulos con tiempos (para reproductores, YouTube, etc.).
- **`.json`** — datos completos: cada segmento, y con `--palabras`, el tiempo de cada palabra.

### Modelos (de más rápido a más preciso)

`tiny` → `base` → `small` → `medium` → **`large-v3`** (por defecto, el mejor).
Tu RTX 4060 (8 GB) corre `large-v3` sin problema.

---

## Notas importantes

- **La PRIMERA transcripción de todas tarda varios minutos** aunque el audio sea corto:
  la GPU compila sus kernels CUDA una única vez y los guarda en caché.
  Después es muy rápido (segundos). No te asustes esa primera vez.
- La primera vez también se descarga el modelo Whisper (~3 GB para `large-v3`) en
  `C:\Users\Edu\.cache\huggingface` y se reutiliza siempre.
- **Todo es offline.** No necesitas internet (salvo la descarga inicial del modelo) ni
  ninguna cuenta ni token.

## Qué se instaló

- Entorno Python aislado en `.venv`: `faster-whisper`, `sherpa-onnx` y librerías CUDA
  (cuBLAS, cuDNN).
- `ffmpeg` (vía winget) para leer cualquier formato.
- Modelos de diarización en `modelos/` (segmentación + huella de voz).
