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
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

import pystray
import webview

from icono import crear_icono

RUTA_CONFIG = Path(__file__).parent / "config.json"

# Guardado junto al programa (no en el cache del WebView, que puede limpiarse o vivir en
# otro perfil): identifica ESTE puesto de trabajo de forma estable entre reinicios del
# programa. Se genera una sola vez, la primera vez que corre en este PC.
RUTA_ID_ESTACION = Path(__file__).parent / "estacion_id.txt"


def cargar_config() -> dict:
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def obtener_id_estacion_persistente() -> str:
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
