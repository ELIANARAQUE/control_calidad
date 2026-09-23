@echo off
REM Genera UN SOLO .exe listo para llevar a cada PC (USB, descarga, etc.) sin ningun
REM archivo aparte que copiar o editar despues: config.json queda incrustado dentro del
REM .exe, y el programa se instala y configura solo la primera vez que se abre.
REM
REM IMPORTANTE: edita config.json con la IP real del servidor ANTES de correr esto --
REM ese valor queda fijo dentro del .exe para todos los PCs a los que lo lleves. Si el
REM servidor cambia de IP mas adelante, hay que volver a construir y redistribuir el .exe.

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

pyinstaller --noconsole --onefile ^
    --add-data "config.json;." ^
    --name ControlCalidadMonitor ^
    app.py

echo.
echo Listo: dist\ControlCalidadMonitor.exe
echo Es el UNICO archivo que hace falta llevar a cada PC. Al abrirlo la primera vez:
echo   - se copia solo a una carpeta permanente del equipo (sigue funcionando aunque
echo     despues saques la USB de donde lo abriste)
echo   - se registra para abrir solo con Windows
echo   - identifica el puesto usando el propio Windows, sin pasos manuales
echo No hace falta instalar Python, copiar ningun otro archivo, ni editar nada en el PC.
