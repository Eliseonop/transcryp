@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem ==========================================================================
rem  Abre el Transcriptor (sin ventana de consola).
rem  Si todavia no esta instalado en esta carpeta, ofrece ejecutar instalar.bat.
rem ==========================================================================
pushd "%~dp0"
if exist ".venv\Scripts\pythonw.exe" if exist ".venv\Lib\site-packages\faster_whisper\__init__.py" goto :abrir

echo.
echo  El Transcriptor todavia no esta instalado en esta carpeta.
set "RESP=S"
set /p "RESP= Instalarlo ahora? [S/n]: "
if /i "%RESP:~0,1%"=="n" goto :salir
call "%~dp0instalar.bat"
goto :salir

:abrir
start "" ".venv\Scripts\pythonw.exe" main.py

:salir
popd
endlocal
exit /b 0
