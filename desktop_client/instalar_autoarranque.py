"""Registra este programa para que arranque solo al iniciar sesion en Windows.

No requiere permisos de administrador: usa la carpeta de Inicio del usuario actual
(`shell:startup`), que Windows ejecuta automaticamente en cada inicio de sesion.

`asegurar_autoarranque()` es lo que llama `app.py` solo, en cada arranque: si el auto-arranque
ya esta configurado no hace nada (no lo reescribe ni pisa un cambio manual), y si no lo
estaba, lo configura sin que nadie tenga que ejecutar este archivo a mano. Por eso instalar
el programa es, en la practica, "copiar la carpeta (o el .exe) y abrirlo una vez".

Tambien se puede usar como script suelto para instalar/quitar explicitamente:
    python instalar_autoarranque.py            # instala (o confirma que ya estaba)
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


def _comando_de_arranque() -> str:
    """El comando que abre este mismo programa, ya sea corriendo como script .py (entorno
    de desarrollo) o ya empaquetado en un .exe con PyInstaller --onefile (`sys.frozen`)."""
    if getattr(sys, "frozen", False):
        # Empaquetado: sys.executable ES el .exe final, no hay un app.py aparte que llamar.
        return f'start "" "{sys.executable}"'

    directorio_app = Path(__file__).parent.resolve()
    python_w = Path(sys.executable).parent / "pythonw.exe"
    if not python_w.exists():
        python_w = Path(sys.executable)  # entorno sin pythonw (ej. algunos venv): usa el interprete normal
    return f'cd /d "{directorio_app}" && start "" "{python_w}" "{directorio_app / "app.py"}"'


def instalar() -> None:
    contenido_bat = f"@echo off\r\n{_comando_de_arranque()}\r\n"
    destino = ruta_bat()
    destino.write_text(contenido_bat, encoding="utf-8")
    print(f"Auto-arranque instalado: {destino}")


def asegurar_autoarranque() -> None:
    """Se llama sola al abrir el programa (ver app.py). Idempotente: si el .bat ya existe
    no hace nada, para no pisar un cambio manual ni reescribirlo en cada arranque."""
    if not ruta_bat().exists():
        instalar()


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
