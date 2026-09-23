"""Registra este programa para que arranque solo al iniciar sesion en Windows.

No requiere permisos de administrador: usa la carpeta de Inicio del usuario actual
(`shell:startup`), que Windows ejecuta automaticamente en cada inicio de sesion.

Uso:
    python instalar_autoarranque.py            # instala
    python instalar_autoarranque.py --quitar   # desinstala
"""
import os
import sys
from pathlib import Path

NOMBRE_TAREA = "ControlCalidadMonitor"


def carpeta_inicio() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def ruta_bat() -> Path:
    return carpeta_inicio() / f"{NOMBRE_TAREA}.bat"


def instalar() -> None:
    directorio_app = Path(__file__).parent.resolve()
    python_w = Path(sys.executable).parent / "pythonw.exe"
    if not python_w.exists():
        python_w = Path(sys.executable)  # entorno sin pythonw (ej. algunos venv): usa el interprete normal

    contenido_bat = (
        f'@echo off\r\n'
        f'cd /d "{directorio_app}"\r\n'
        f'start "" "{python_w}" "{directorio_app / "app.py"}"\r\n'
    )

    destino = ruta_bat()
    destino.write_text(contenido_bat, encoding="utf-8")
    print(f"Auto-arranque instalado: {destino}")
    print("El programa se abrira automaticamente en el proximo inicio de sesion de Windows.")


def quitar() -> None:
    destino = ruta_bat()
    if destino.exists():
        destino.unlink()
        print(f"Auto-arranque eliminado: {destino}")
    else:
        print("No habia auto-arranque instalado.")


if __name__ == "__main__":
    if "--quitar" in sys.argv:
        quitar()
    else:
        instalar()
