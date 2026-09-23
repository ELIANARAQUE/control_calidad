"""Programa de escritorio para el puesto del empleado.

Es una ventana de navegador embebido (WebView2 en Windows) SIN barra de direcciones,
menus ni controles de navegacion, apuntando directo al panel web del empleado que ya
sirve el backend (`/empleado/`). No duplica el frontend: lo reutiliza tal cual.

Pensado para distribuirse como UN SOLO .exe (ver build.bat): se lleva en una USB o se
descarga, se abre una vez, y queda listo -sin archivos sueltos que copiar o editar en
cada PC-. En ese primer arranque:
  1. Se copia solo a una carpeta permanente del equipo (por si se abrio desde la USB y
     luego se la sacan -si no hiciera esto, el auto-arranque apuntaria a un archivo que
     ya no existe).
  2. Se registra para abrir solo en el proximo inicio de sesion de Windows.
  3. Identifica el puesto usando el MachineGuid que Windows ya genera por instalacion
     (no un archivo que se pueda copiar por error entre PCs).
  4. Levanta un proxy local (ver proxy_local.py) para que la pagina se cargue desde
     "localhost" en vez de la IP del servidor -asi la camara/microfono funcionan dentro
     de WebView2, que como cualquier navegador moderno los bloquea fuera de un "contexto
     seguro" (HTTPS o localhost)-.

Se ejecuta en segundo plano con icono en la bandeja del sistema: cerrar la ventana la
minimiza (no termina el proceso), y solo "Salir" desde el icono de bandeja lo detiene.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

import pystray
import webview

from icono import crear_icono
from instalar_autoarranque import asegurar_autoarranque
from proxy_local import iniciar_proxy_local

logger = logging.getLogger(__name__)

NOMBRE_EXE = "ControlCalidadMonitor.exe"


def _directorio_datos_persistentes() -> Path:
    """Carpeta de trabajo permanente del programa (en el perfil del usuario de Windows),
    independiente de desde donde se haya ejecutado el .exe (USB, Descargas, etc.). Ahi
    vive la copia "instalada" del programa y el id de estacion de respaldo.
    """
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ControlCalidadMonitor"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _recursos_empaquetados() -> Path:
    """Carpeta de solo lectura con lo que va embebido dentro del .exe (PyInstaller
    --onefile lo descomprime en una carpeta temporal -`sys._MEIPASS`- en cada arranque).
    En modo desarrollo (`python app.py`) es simplemente la carpeta de este archivo.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent


RUTA_CONFIG = _recursos_empaquetados() / "config.json"

# Respaldo si no se puede leer el identificador de Windows (ver obtener_id_estacion_persistente).
RUTA_ID_ESTACION = _directorio_datos_persistentes() / "estacion_id.txt"


def cargar_config() -> dict:
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def _autoinstalar_si_hace_falta() -> None:
    """Si el .exe no se esta ejecutando ya desde su ubicacion permanente (primer arranque
    desde una USB, carpeta de Descargas, etc.), se copia ahi y se relanza desde la copia
    -esta funcion no vuelve en ese caso, el proceso actual termina-.
    """
    if not getattr(sys, "frozen", False):
        return  # en modo desarrollo (python app.py) no aplica

    exe_actual = Path(sys.executable).resolve()
    exe_instalado = (_directorio_datos_persistentes() / NOMBRE_EXE).resolve()

    if exe_actual == exe_instalado:
        return  # ya se esta ejecutando desde la copia instalada

    try:
        shutil.copy2(exe_actual, exe_instalado)
    except OSError:
        logger.exception("No se pudo copiar el programa a una ubicacion permanente; sigue corriendo desde aqui")
        return

    subprocess.Popen([str(exe_instalado)], close_fds=True)
    sys.exit(0)


def _machine_guid_de_windows() -> str | None:
    """Windows genera un identificador unico por instalacion (MachineGuid) que ya vive en
    el registro de cada equipo -no hay que generarlo ni copiarlo nosotros-. Usarlo evita
    por completo el problema de "si copio el .exe a otro PC, comparten id": cada Windows
    tiene el suyo, sin importar que archivos se hayan copiado.
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
    # un id generado una sola vez y guardado en la carpeta de datos permanente.
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
    o pedir esos datos el mismo. Carga la pagina a traves del proxy local (ver
    proxy_local.py) en vez de la IP del servidor directo, para que la camara/microfono
    funcionen dentro de WebView2 (exigen un "contexto seguro": HTTPS o localhost).
    """
    servidor_original = urlparse(config["servidor_url"])
    base_local = iniciar_proxy_local(config["servidor_url"])
    ruta = servidor_original.path or "/empleado/"

    estacion_id = obtener_id_estacion_persistente()
    url = f"{base_local}{ruta}?estacion_id={estacion_id}"

    nombre_empleado = config.get("empleado_nombre", "").strip()
    if nombre_empleado:
        url += f"&nombre={quote(nombre_empleado)}"

    return url


def main() -> None:
    _autoinstalar_si_hace_falta()  # si aplica, esta funcion no vuelve (el proceso termina)

    try:
        asegurar_autoarranque()
    except Exception:
        # Que falle el auto-arranque no debe impedir que el programa abra: en el peor
        # caso, alguien tiene que abrirlo a mano cada vez.
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
