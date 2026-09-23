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
from pathlib import Path

import pystray
import webview

from icono import crear_icono

RUTA_CONFIG = Path(__file__).parent / "config.json"


def cargar_config() -> dict:
    with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    config = cargar_config()

    ventana = webview.create_window(
        config["titulo_ventana"],
        config["servidor_url"],
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
