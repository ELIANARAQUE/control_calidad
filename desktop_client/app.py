"""Programa de escritorio para el puesto del empleado.

Es una ventana de navegador embebido (WebView2 en Windows) SIN barra de direcciones,
menus ni controles de navegacion, apuntando directo al panel web del empleado que ya
sirve el backend (`/empleado/`). No duplica el frontend: lo reutiliza tal cual.

Se ejecuta en segundo plano con icono en la bandeja del sistema: cerrar la ventana la
minimiza (no termina el proceso), y solo "Salir" desde el icono de bandeja lo detiene.
Pensado para arrancar automaticamente al iniciar sesion en Windows (ver
`instalar_autoarranque.py`).
"""
import json
import logging
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

import pystray
import webview

from icono import crear_icono
from instalar_autoarranque import asegurar_autoarranque

logger = logging.getLogger(__name__)


def _directorio_programa() -> Path:
    """Carpeta donde vive el programa de verdad -para leer/guardar archivos junto a el-.

    Importante bajo PyInstaller --onefile: `Path(__file__).parent` apuntaria a la carpeta
    temporal donde se descomprime el .exe en cada arranque (se borra despues), NO a donde
    esta el .exe. Ahi `config.json` no se podria editar por PC sin recompilar. Se usa
    `sys.executable` (la ruta del .exe) cuando esta empaquetado, y `__file__` en desarrollo.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


RUTA_CONFIG = _directorio_programa() / "config.json"

# Respaldo si no se puede leer el identificador de Windows (ver obtener_id_estacion_persistente):
# un id generado una sola vez y guardado junto al programa.
RUTA_ID_ESTACION = _directorio_programa() / "estacion_id.txt"


def cargar_config() -> dict:
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def _machine_guid_de_windows() -> str | None:
    """Windows genera un identificador unico por instalacion (MachineGuid) que ya vive en
    el registro de cada equipo -no hay que generarlo ni copiarlo nosotros-. Usarlo evita
    por completo el problema de "si copio la carpeta a otro PC, comparten id": cada
    Windows tiene el suyo, sin importar que archivos se hayan copiado.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as clave:
            valor, _ = winreg.QueryValueEx(clave, "MachineGuid")
            return valor
    except OSError:
        logger.warning("No se pudo leer el MachineGuid de Windows; se usara un id de respaldo en disco")
        return None


def obtener_id_estacion_persistente() -> str:
    guid_maquina = _machine_guid_de_windows()
    if guid_maquina:
        return f"pc-{guid_maquina}"

    # Respaldo (equipos no-Windows, o si por algun motivo no se pudo leer el registro):
    # un id generado una sola vez y guardado en disco junto al programa. Ojo: a diferencia
    # del MachineGuid, ESTE si viaja si se copia la carpeta ya usada a otro equipo.
    if RUTA_ID_ESTACION.exists():
        id_guardado = RUTA_ID_ESTACION.read_text(encoding="utf-8").strip()
        if id_guardado:
            return id_guardado

    nuevo_id = str(uuid.uuid4())
    RUTA_ID_ESTACION.write_text(nuevo_id, encoding="utf-8")
    return nuevo_id


def construir_url(config: dict) -> str:
    """Agrega el id de estacion (y el nombre del empleado, si esta preconfigurado en
    config.json) como parametros de URL, para que el frontend los use en vez de generar
    o pedir esos datos el mismo."""
    estacion_id = obtener_id_estacion_persistente()
    separador = "&" if "?" in config["servidor_url"] else "?"
    url = f'{config["servidor_url"]}{separador}estacion_id={estacion_id}'

    nombre_empleado = config.get("empleado_nombre", "").strip()
    if nombre_empleado:
        url += f"&nombre={quote(nombre_empleado)}"

    return url


def main() -> None:
    try:
        asegurar_autoarranque()
    except Exception:
        # Que falle el auto-arranque no debe impedir que el programa abra: en el peor
        # caso, alguien tiene que abrirlo a mano una vez y ya (o correr el instalador
        # de nuevo con permisos distintos).
        logger.exception("No se pudo configurar el auto-arranque automaticamente")

    config = cargar_config()

    ventana = webview.create_window(
        config["titulo_ventana"],
        construir_url(config),
        width=config["ancho"],
        height=config["alto"],
        resizable=True,
        text_select=False,
    )

    def al_cerrar() -> bool:
        # Devolver False cancela el cierre real: la ventana solo se oculta,
        # asi la transmision de video/audio hacia el servidor sigue activa.
        ventana.hide()
        return False

    ventana.events.closing += al_cerrar

    def iniciar_bandeja() -> None:
        def mostrar(icon, item) -> None:
            ventana.show()

        def salir(icon, item) -> None:
            icon.stop()
            ventana.destroy()

        menu = pystray.Menu(
            pystray.MenuItem("Mostrar panel", mostrar, default=True),
            pystray.MenuItem("Salir", salir),
        )
        icono_bandeja = pystray.Icon("qa_monitor", crear_icono(), config["titulo_ventana"], menu)
        icono_bandeja.run()

    hilo_bandeja = threading.Thread(target=iniciar_bandeja, daemon=True)
    hilo_bandeja.start()

    webview.start()


if __name__ == "__main__":
    main()
