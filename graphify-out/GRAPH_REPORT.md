# Graph Report - transcryp  (2026-10-22)

## Corpus Check
- 10 files · ~5,487 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 130 nodes · 218 edges · 14 communities (13 shown, 1 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 4 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9c8fe9ac`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- App
- Forma por línea de comandos
- gui.py
- config.py
- setup_modelos.py
- Path
- lanzar
- transcribir.py
- obtener_segmentos
- abrir_transcripcion
- _cargar_dlls_cuda
- tam_lote
- imprimir_fases
- __init__.py

## God Nodes (most connected - your core abstractions)
1. `App` - 29 edges
2. `obtener_segmentos()` - 8 edges
3. `limpiar_nombre()` - 7 edges
4. `ruta_txt_libre()` - 6 edges
5. `transcribir_archivo()` - 6 edges
6. `main()` - 6 edges
7. `_leer_json()` - 5 edges
8. `carpeta_cursos()` - 5 edges
9. `guardar_carpeta_cursos()` - 5 edges
10. `duracion_segundos()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `lanzar()`  [EXTRACTED]
  main.py → app/gui.py

## Import Cycles
- None detected.

## Communities (14 total, 1 thin omitted)

### Community 0 - "App"
Cohesion: 0.11
Nodes (7): App, dur_bonita(), duracion_segundos(), Path, Una carpeta por curso y dentro solo el .txt: <Curso>\\<nombre del video>.txt, Duracion del medio usando ffprobe (viene con ffmpeg). None si falla., tipo_de()

### Community 1 - "Forma por línea de comandos"
Cohesion: 0.12
Nodes (15): Forma fácil (la aplicación), Forma por línea de comandos, Formatos de salida, Modelos (de más rápido a más preciso), Notas importantes, Opciones, Qué se instaló, Transcriptor local (offline) (+7 more)

### Community 2 - "gui.py"
Cohesion: 0.19
Nodes (11): Interfaz grafica del transcriptor local (faster-whisper). - Arrastra un video o…, Convierte segmentos en texto plano legible (con hablantes si los hay)., texto_de_segmentos(), limpiar_nombre(), Path, Utilidades para guardar transcripciones por CURSO. Cada curso es una sola…, Quita caracteres no validos para nombres de carpeta en Windows., Cuantos .txt hay ya guardados en la carpeta del curso. (+3 more)

### Community 3 - "config.py"
Cohesion: 0.26
Nodes (13): agregar_curso(), cargar_cursos(), carpeta_cursos(), _carpeta_cursos_por_defecto(), _escribir_json(), guardar_carpeta_cursos(), _leer_json(), Path (+5 more)

### Community 4 - "setup_modelos.py"
Cohesion: 0.29
Nodes (9): _descargar(), faltan_modelos(), _mb(), Path, Verificacion y descarga de los modelos de diarizacion (separar hablantes).…, True si falta alguno de los modelos de diarizacion., Descarga 'url' a 'destino' de forma atomica, informando el progreso., Descarga lo que falte. Devuelve True si al final esta todo listo. 'log' es una… (+1 more)

### Community 5 - "Path"
Cohesion: 0.36
Nodes (8): cargar_diarizador(), escribir_json(), escribir_txt(), guardar(), main(), Path, Escribe los formatos pedidos usando destino_base (sin extension)., transcribir_archivo()

### Community 6 - "lanzar"
Cohesion: 0.47
Nodes (5): lanzar(), _asegurar_venv(), main(), Punto de entrada del Transcriptor. Abre la interfaz grafica (arrastra un…, Si nos abren con otro Python (PyCharm, doble clic, python del sistema), relanza…

### Community 7 - "transcribir.py"
Cohesion: 0.60
Nodes (5): escribir_srt(), escribir_vtt(), formato_tiempo(), _prefijo(), Transcriptor local de audio/video (mp4, wav, mp3, mkv, m4a, etc.) Usa faster-…

### Community 8 - "obtener_segmentos"
Cohesion: 0.40
Nodes (5): diarizar(), hablante_de(), obtener_segmentos(), Devuelve el hablante que mas se solapa con [inicio, fin]., Transcribe (y opcionalmente diariza) un archivo. Devuelve lista de segmentos.

### Community 9 - "abrir_transcripcion"
Cohesion: 0.50
Nodes (4): abrir_transcripcion(), _crear_pipeline(), Envuelve el modelo en un pipeline por lotes (BatchedInferencePipeline).…, Inicia la transcripcion y devuelve (iterador_de_segmentos, info). Si lote > 1 y…

### Community 10 - "_cargar_dlls_cuda"
Cohesion: 0.50
Nodes (4): _cargar_dlls_cuda(), cargar_modelo(), Carga WhisperModel eligiendo GPU/CPU. Devuelve (modelo, device, compute). En…, En Windows anade las carpetas bin de cuBLAS/cuDNN (instaladas via pip) al…

### Community 11 - "tam_lote"
Cohesion: 0.50
Nodes (4): VRAM libre de la GPU (MB) via nvidia-smi. None si no se puede saber., Tamano de lote recomendado segun dispositivo, modelo y VRAM. En GPU se pueden…, tam_lote(), _vram_libre_mb()

### Community 12 - "imprimir_fases"
Cohesion: 0.67
Nodes (3): imprimir_fases(), mmss(), Formatea una duracion como 'X min Y s'.

## Knowledge Gaps
- **11 isolated node(s):** `Forma fácil (la aplicación)`, `Un solo archivo o una CARPETA entera (lote)`, `Opciones`, `Formatos de salida`, `Modelos (de más rápido a más preciso)` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 46 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `App` connect `App` to `gui.py`, `lanzar`?**
  _High betweenness centrality (0.264) - this node is a cross-community bridge._
- **Why does `lanzar()` connect `lanzar` to `App`, `gui.py`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `ruta_txt_libre()` connect `gui.py` to `App`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **What connects `Forma fácil (la aplicación)`, `Un solo archivo o una CARPETA entera (lote)`, `Opciones` to the rest of the system?**
  _11 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `App` be split into smaller, more focused modules?**
  _Cohesion score 0.11491935483870967 - nodes in this community are weakly interconnected._
- **Should `Forma por línea de comandos` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._