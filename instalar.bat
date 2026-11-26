@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem ==========================================================================
rem  Instalador del Transcriptor (Windows 10/11)
rem
rem  Doble clic en este archivo y sigue los mensajes. Hace esto:
rem    1. Busca Python 3.10 a 3.14 de 64 bits. Si no hay, ofrece instalar
rem       Python 3.14 con winget.
rem    2. Crea el entorno aislado .venv dentro de esta carpeta.
rem    3. Instala las librerias de requirements.txt. Las de GPU NVIDIA (CUDA)
rem       solo si detecta una tarjeta NVIDIA; sin ella el programa usa la CPU.
rem       Despues comprueba el runtime de Visual C++ y que todo carga.
rem    4. Comprueba ffmpeg (opcional) y, si falta, ofrece instalarlo.
rem
rem  Se puede ejecutar las veces que haga falta: reutiliza lo que ya esta
rem  instalado y completa lo que falte.
rem
rem  Opciones, desde una terminal:
rem    instalar.bat cpu    sin las librerias de GPU
rem    instalar.bat gpu    con las librerias de GPU aunque no detecte NVIDIA
rem ==========================================================================

title Instalador del Transcriptor
pushd "%~dp0"
if not exist "requirements.txt" goto :error_carpeta
if not exist "main.py" goto :error_carpeta

set "VENV_PY=.venv\Scripts\python.exe"
rem Con el nuevo "Python install manager", "py -3.x" podria instalar solo una
rem version que falte al buscarla; aqui solo queremos preguntar si existe.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"

set "MODO=%~1"
if "%MODO%"=="" goto :inicio
if /i "%MODO%"=="cpu" goto :inicio
if /i "%MODO%"=="gpu" goto :inicio
echo  Opcion desconocida: %MODO%
echo  Uso: instalar.bat, instalar.bat cpu o instalar.bat gpu
goto :fallo

:inicio
echo.
echo  ==========================================
echo    Instalador del Transcriptor
echo  ==========================================

rem -------------------------------------------------------------- 1) Python
echo.
echo  [1/4] Buscando Python 3.10 a 3.14 ...
call :buscar_python
if defined PY goto :python_ok
echo        No se encontro Python 3.10 a 3.14 de 64 bits.
where winget >nul 2>&1
if errorlevel 1 goto :python_manual
set "RESP=S"
set /p "RESP=       Instalar Python 3.14 ahora con winget? [S/n]: "
if /i "%RESP:~0,1%"=="n" goto :python_manual
winget install -e --id Python.Python.3.14
call :buscar_python
if defined PY goto :python_ok
echo.
echo        Python ya esta instalado, pero esta ventana aun no lo ve.
echo        Cierrala y vuelve a abrir instalar.bat.
goto :fallo

:python_manual
echo.
echo        Instala Python 3.14 desde https://www.python.org/downloads/
echo        marcando "Add python.exe to PATH" y vuelve a abrir instalar.bat.
goto :fallo

:python_ok
%PY% -c "import sys; print('       OK: Python', sys.version.split()[0], 'en', sys.executable)"

rem --------------------------------------------------------------- 2) .venv
echo.
echo  [2/4] Preparando el entorno aislado .venv ...
if not exist "%VENV_PY%" goto :crear_venv
"%VENV_PY%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto :venv_ok
echo        El .venv que habia no funciona; se crea de nuevo.
rmdir /s /q ".venv"
if exist ".venv" goto :error_borrar_venv
:crear_venv
echo        Creando .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :error_venv
if not exist "%VENV_PY%" goto :error_venv
:venv_ok
"%VENV_PY%" -c "import sys; print('       OK: .venv con Python', sys.version.split()[0])"
echo        Actualizando pip ...
"%VENV_PY%" -m pip install --upgrade pip --disable-pip-version-check --quiet
if errorlevel 1 echo        Aviso: no se pudo actualizar pip; se sigue con el que hay.

rem ----------------------------------------------------------- 3) librerias
echo.
echo  [3/4] Instalando librerias ...
set "GPU="
if /i "%MODO%"=="gpu" set "GPU=1"
if /i "%MODO%"=="cpu" goto :elegir_req
if defined GPU goto :elegir_req
nvidia-smi -L >nul 2>&1
if not errorlevel 1 set "GPU=1"
:elegir_req
if defined GPU goto :req_gpu
echo        Version para CPU: sin las librerias de GPU NVIDIA.
findstr /v /i /r /c:"^nvidia-" "requirements.txt" > ".venv\requirements-cpu.txt"
set "REQ=.venv\requirements-cpu.txt"
goto :pip_install
:req_gpu
echo        Version con GPU NVIDIA: incluye las librerias CUDA.
echo        La primera vez descarga unos 2-3 GB; puede tardar varios minutos.
set "REQ=requirements.txt"
:pip_install
"%VENV_PY%" -m pip install --disable-pip-version-check --prefer-binary -r "%REQ%"
if errorlevel 1 goto :error_pip

rem Varias librerias necesitan el runtime de Visual C++ de Microsoft.
if exist "%SystemRoot%\System32\msvcp140.dll" if exist "%SystemRoot%\System32\vcruntime140_1.dll" goto :vc_ok
echo        Falta el runtime de Microsoft Visual C++ que usan estas librerias.
where winget >nul 2>&1
if errorlevel 1 goto :vc_ok
set "RESP=S"
set /p "RESP=       Instalarlo ahora con winget? Pedira permiso de administrador. [S/n]: "
if /i "%RESP:~0,1%"=="n" goto :vc_ok
winget install -e --id Microsoft.VCRedist.2015+.x64
:vc_ok

echo        Comprobando que todo carga ...
"%VENV_PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :error_tk
"%VENV_PY%" -c "import faster_whisper, sherpa_onnx"
if errorlevel 1 goto :error_import
echo        OK: librerias instaladas.
if not defined GPU goto :ffmpeg
"%VENV_PY%" -c "import transcribir as T; T._cargar_dlls_cuda(); import ctranslate2 as c; raise SystemExit(0 if c.get_cuda_device_count() else 1)" >nul 2>&1
if errorlevel 1 goto :gpu_no
echo        OK: GPU NVIDIA lista.
goto :ffmpeg
:gpu_no
echo        Aviso: la GPU no responde; el programa usara la CPU, mas lento.
echo        Si quieres usar la GPU, actualiza el driver de NVIDIA.

rem -------------------------------------------------------------- 4) ffmpeg
:ffmpeg
echo.
echo  [4/4] Comprobando ffmpeg ...
where ffprobe >nul 2>&1
if not errorlevel 1 goto :ffmpeg_ok
echo        No se encontro ffmpeg. Es opcional: sirve para ver la duracion
echo        de cada video en la cola antes de transcribir.
where winget >nul 2>&1
if errorlevel 1 goto :ffmpeg_manual
set "RESP=S"
set /p "RESP=       Instalar ffmpeg ahora con winget? [S/n]: "
if /i "%RESP:~0,1%"=="n" goto :ffmpeg_manual
winget install -e --id Gyan.FFmpeg
if errorlevel 1 goto :ffmpeg_manual
echo        OK: ffmpeg instalado; se usara la proxima vez que abras el programa.
goto :fin
:ffmpeg_manual
echo        Puedes instalarlo cuando quieras con:  winget install ffmpeg
goto :fin
:ffmpeg_ok
echo        OK: ffmpeg encontrado.

rem ------------------------------------------------------------------- fin
:fin
echo.
echo  ==========================================
echo    Instalacion completa.
echo    Para abrir el programa: doble clic en iniciar.bat
echo  ==========================================
echo.
set "RESP=S"
set /p "RESP=  Abrir el Transcriptor ahora? [S/n]: "
if /i not "%RESP:~0,1%"=="n" start "" ".venv\Scripts\pythonw.exe" main.py
popd
endlocal
exit /b 0

rem --------------------------------------------------------------- errores
:error_carpeta
echo.
echo  ERROR: instalar.bat tiene que estar en la carpeta del programa,
echo  junto a main.py y requirements.txt.
goto :fallo

:error_borrar_venv
echo.
echo  ERROR: no se pudo borrar la carpeta .venv. Cierra el Transcriptor
echo  y vuelve a abrir instalar.bat.
goto :fallo

:error_venv
echo.
echo  ERROR: no se pudo crear el entorno .venv. Mira el mensaje de arriba.
goto :fallo

:error_pip
echo.
echo  ERROR: fallo la instalacion de las librerias. Revisa la conexion a
echo  internet y vuelve a abrir instalar.bat: retoma lo que falte.
echo  Si sigue fallando, borra la carpeta .venv y prueba otra vez.
goto :fallo

:error_tk
echo.
echo  ERROR: a este Python le falta tkinter, la parte de las ventanas.
echo  Reinstala Python marcando "tcl/tk and IDLE" y vuelve a abrir instalar.bat.
goto :fallo

:error_import
echo.
echo  ERROR: las librerias se instalaron pero no cargan; mira el mensaje de
echo  arriba. Si habla de una DLL, instala el runtime de Visual C++ con:
echo      winget install Microsoft.VCRedist.2015+.x64
echo  y vuelve a abrir instalar.bat.
goto :fallo

:fallo
echo.
pause
popd
endlocal
exit /b 1

rem ============================================================ subrutinas

:buscar_python
rem Deja en PY el comando de un Python 3.10 a 3.14 de 64 bits, o PY vacio.
set "PY="
rem a) El lanzador "py" que instala python.org.
for %%V in (3.14 3.13 3.12 3.11 3.10) do if not defined PY call :probar py -%%V
if defined PY exit /b 0
rem b) "python" del PATH.
call :probar python
if defined PY exit /b 0
rem c) Carpetas de instalacion habituales: Python sin PATH o recien instalado.
for %%V in (3.14 3.13 3.12 3.11 3.10) do if not defined PY call :probar_carpetas %%V
exit /b 0

:probar_carpetas
set "_N=%~1"
set "_N=%_N:.=%"
call :probar "%LOCALAPPDATA%\Programs\Python\Python%_N%\python.exe"
if not defined PY call :probar "%ProgramFiles%\Python%_N%\python.exe"
if not defined PY call :probar "%LOCALAPPDATA%\Python\pythoncore-%~1-64\python.exe"
exit /b 0

:probar
rem Recibe el comando a probar; lo acepta si es Python 3.10 a 3.14 de 64 bits.
%* -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PY=%*"
exit /b 0
