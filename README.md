# Transcryp — Transcriptor local (offline)

Transcribe cualquier **video o audio** (mp4, mkv, mov, wav, mp3, m4a, flac…) a
texto. Funciona **100 % en tu computadora**, sin cuentas ni tokens, y aprovecha
tu **GPU NVIDIA** si la tienes.

- Motor de voz: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (modelo Whisper).
- Separar hablantes: [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx).
- Traductor en vivo inglés → español:
  [Argos Translate](https://github.com/argosopentech/argos-translate) sin internet,
  u opcionalmente Google Translate (gratis, sin cuenta).

---

## Instalar (desde cero)

Solo hace falta **Windows 10/11** e internet la primera vez.

1. **Descarga el programa**: en [Releases](https://github.com/Eliseonop/transcryp/releases/latest),
   **Source code (zip)**, y descomprímelo donde quieras (o clónalo con
   `git clone https://github.com/Eliseonop/transcryp.git`).
2. **Doble clic en `instalar.bat`** y sigue los mensajes. El instalador:
   - busca **Python 3.10 a 3.14** y, si no lo tienes, ofrece instalar Python 3.14
     con `winget`;
   - crea el entorno aislado `.venv` dentro de la carpeta del programa;
   - instala las librerías de `requirements.txt`: las de **GPU NVIDIA** (CUDA,
     unos 2–3 GB) solo si detecta una tarjeta NVIDIA; si no, la versión para
     **CPU**;
   - comprueba que todo carga, incluido el runtime de Visual C++ que usan las
     librerías (si falta, ofrece instalarlo);
   - comprueba **ffmpeg** (opcional: muestra la duración de cada video en la
     cola) y, si falta, ofrece instalarlo;
   - al terminar, pregunta si quieres abrir el programa.
3. Para abrirlo después: **doble clic en `iniciar.bat`**.

> - Si Windows avisa de que el archivo viene de internet, elige **Ejecutar**
>   (o **Más información → Ejecutar de todas formas**).
> - Puedes repetir `instalar.bat` cuando quieras: reutiliza lo instalado y
>   completa lo que falte (por ejemplo, si se cortó la descarga).
> - Para elegir a mano CPU o GPU, ejecútalo desde una terminal:
>   `.\instalar.bat cpu` o `.\instalar.bat gpu`.
> - La primera transcripción descarga además el modelo de voz (~3 GB, ver
>   [Modelos que se descargan solos](#modelos-que-se-descargan-solos)).

<details>
<summary>Instalación manual (sin el .bat)</summary>

Necesitas **Python 3.10 a 3.14** y, opcionalmente, **ffmpeg**.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
winget install ffmpeg
```

Si **no** tienes GPU NVIDIA, comenta antes las líneas `nvidia-*` de
`requirements.txt`: el programa usará la CPU automáticamente.

</details>

## Usar

**Doble clic en `iniciar.bat`** (si aún no está instalado, ofrece instalarlo).
O desde una terminal:

```powershell
.\.venv\Scripts\python main.py
```

Se abre la ventana: arrastra un video/audio, elige idioma y pulsa **Transcribir**.

### Varios archivos a la vez (cola)

Arrastra **varios** videos/audios, o una **carpeta** entera (se incluyen sus
subcarpetas), o usa **📂 Elegir archivos…** / **🗂 Agregar carpeta…**. Todo entra
en la **cola**, ordenado por nombre (`Clase 2` va antes que `Clase 10`). Con
**▶ Transcribir** se procesan uno tras otro.

- Mientras la cola está parada, los pendientes usan las opciones que tengas
  marcadas (idioma, calidad, curso). Al pulsar **Transcribir** quedan fijadas, así
  que puedes cambiar de curso y seguir arrastrando archivos para otro curso.
- **⏹ Detener** para la cola; el archivo que se estaba transcribiendo vuelve a
  quedar pendiente.
- Haz clic en una fila terminada para ver su texto. **✖ Quitar** (o `Supr`) saca
  archivos de la cola y **🧹 Limpiar terminados** borra de la lista los ya hechos.
- Sin curso, si la cola tiene varios archivos, también se guardan los cortos en
  `Escritorio\Transcripciones` para no perder ninguno.

### Guardar organizado por curso (opcional)

Marca **Guardar organizado por curso**, elige la **carpeta** donde se guardan y
añade cursos con **➕ Curso**. Tus cursos quedan en un `cursos.json` local (no se
sube al repositorio; usa [`cursos.example.json`](cursos.example.json) como
referencia). Cada curso es una sola carpeta y cada transcripción se guarda ahí
como `.txt` con el nombre del video: `…\<Curso>\<nombre del video>.txt`.

### Traductor en vivo (inglés → español)

Pulsa **🌐 Traductor en vivo (EN→ES)**. Se abre una ventana que **escucha** y
muestra en dos columnas **lo que se escucha** (inglés) y, **al lado, la
traducción** al español:

1. En **Escuchar** elige *Lo que suena en el PC* (capta cualquier video, clase o
   reunión que se esté reproduciendo) o un **micrófono**.
2. Pulsa **▶ Escuchar**. Mientras alguien habla, la frase en curso aparece en gris;
   cuando hace una pausa, queda fija y traducida.
3. **⏹ Detener** para parar.

**Copiar:** **selecciona con el ratón** las frases que quieras (una palabra, una
frase o muchas seguidas, del lado en inglés o del traducido) y cópialas con
**Ctrl+C** o con el **clic derecho**, que además permite copiar esas mismas frases
en los dos idiomas. **Ctrl+A** selecciona toda la columna y los botones **Copiar
todo** copian todo de una vez. También puedes guardarlo como texto bilingüe
(`.txt`) o como **subtítulos en español** (`.srt`).

También traduce un **archivo** entero (**📂 Traducir un archivo…** o arrastrándolo
a la tabla): sale frase a frase y puedes guardar `<video>.es.srt` junto al video.

- **Traductor**: *Local* (por defecto: sin internet y sin límites; descarga
  ~90 MB la primera vez) o *Google* (gratis y sin cuenta, suena algo más natural,
  pero tiene un **límite de uso**: si se alcanza, Google queda en pausa un rato,
  se usa el local y las frases pendientes se reintentan solas). La frase en curso
  (en gris) siempre se traduce con el local.
- **Calidad**: `medium` va bien en tiempo real con GPU; en CPU usa `small` o
  `base`. Si la ventana principal ya cargó ese mismo modelo, se reutiliza.
- **Siempre visible** deja la ventana encima del video y **A− / A+** cambian el
  tamaño de la letra. Tus opciones se recuerdan en `config.json`.

### Modelos que se descargan solos

Nada pesado viaja en el repositorio. Se descarga automáticamente la primera vez:

| Qué | Cuándo | Dónde queda |
|-----|--------|-------------|
| Modelo Whisper (~3 GB) | 1ª transcripción | caché de HuggingFace |
| Modelos de hablantes (~34 MB) | al usar **Separar quien habla**, o con el botón **🔧 Verificar / Preparar** | carpeta `modelos/` |
| Traductor local (~90 MB) | al elegir **Traductor: Local (sin internet)** | carpeta `modelos/traduccion/` |

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
