@echo off
REM Empaqueta el cliente de escritorio como un unico .exe, para poder copiarlo a cada
REM PC de empleado sin que necesiten tener Python instalado. Ver README.md para el
REM flujo completo de instalacion en cada equipo.

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller
)

REM config.json NO se empaqueta dentro del .exe a proposito: tiene que quedar como
REM archivo editable junto al .exe, para poder poner la IP del servidor (y el nombre
REM del empleado) por PC sin recompilar nada.
pyinstaller --noconsole --onefile ^
    --name ControlCalidadMonitor ^
    app.py

if not exist dist\config.json copy config.json dist\config.json >nul

echo.
echo Listo: dist\ControlCalidadMonitor.exe (junto a dist\config.json)
echo.
echo Copia AMBOS archivos (el .exe y config.json) a cada PC, edita config.json con la IP
echo real del servidor, y abre el .exe una vez -- el auto-arranque y el id de estacion
echo se configuran solos, no hace falta ningun otro paso.
