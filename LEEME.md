# Transcriptor local (offline)

Transcribe cualquier video o audio (**mp4, mkv, mov, avi, wav, mp3, m4a, flac, ogg...**)
a texto. Funciona **100% en tu computadora, sin internet**, y usa tu **GPU RTX 4060**
para ir rápido.

Motor: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (modelo Whisper de OpenAI)
+ [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) para separar hablantes.

---

## Forma fácil (la aplicación)

¿Primera vez en este equipo? Doble clic en **`instalar.bat`**: busca Python, crea
el entorno `.venv` e instala todo (detalles en [README.md](README.md#instalar-desde-cero)).

Después, para abrirla: **doble clic en `iniciar.bat`**, o desde una terminal:

```powershell
.\.venv\Scripts\python.exe main.py
```

Se abre la ventana: **arrastra** el video/audio, elige idioma/calidad y pulsa
**Transcribir**. Opciones útiles dentro de la app:

- **Varios a la vez** → arrastra varios archivos o una carpeta entera: entran en
  una **cola** y se transcriben uno tras otro. Con **⏹ Detener** se para la cola,
  y si haces clic en una fila ves su texto.
- **Separar quien habla** → identifica Hablante 1, 2…
- **Guardar organizado por curso** → elige la **carpeta** donde se guardan los
  cursos y añade cursos con **➕ Curso** (se guardan en tu `cursos.json` local).
  Cada transcripción queda solo como `.txt` en la carpeta del curso, con el
  nombre del video: `…\<Curso>\<nombre del video>.txt`.
- **🌐 Traductor en vivo (EN→ES)** → escucha lo que suena en el PC (o el
  micrófono) y muestra lo que se escucha en inglés y, al lado, la traducción al
  español. También traduce un archivo entero y guarda subtítulos `.srt` en
  español. Traductor: *Local* (sin internet, por defecto) o *Google* (gratis, con
  internet y con límite de uso). Selecciona con el ratón las frases que quieras
  (de cualquiera de los dos lados) y cópialas con **Ctrl+C** o el clic derecho.

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
  ninguna cuenta ni token. Única excepción, opcional: el traductor en vivo con
  *Google* envía las frases a Google Translate; elige *Local (sin internet)* para
  que todo siga en tu PC.

## Qué se instaló

`instalar.bat` deja listo lo siguiente (los modelos se descargan solos la primera
vez que se usan):

- Entorno Python aislado en `.venv`: `faster-whisper`, `sherpa-onnx` y librerías CUDA
  (cuBLAS, cuDNN; solo si hay GPU NVIDIA). Para el traductor en vivo: `soundcard`
  (escuchar el audio del PC) y `sentencepiece` (traductor local).
- `ffmpeg` (vía winget), opcional: muestra la duración de cada video en la cola.
  Los formatos los lee `faster-whisper` por su cuenta.
- Modelos de diarización en `modelos/` (segmentación + huella de voz).
