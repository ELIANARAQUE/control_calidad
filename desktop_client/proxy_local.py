"""Proxy HTTP minimo, en 127.0.0.1, que reenvia todo al servidor real.

Por que hace falta: los navegadores (y WebView2, que es Chromium por debajo) solo
permiten `getUserMedia` (camara/microfono) en "contextos seguros" -HTTPS, o localhost,
como caso especial-. El servidor de control de calidad vive en la LAN por IP simple
(HTTP), asi que cargando esa URL directo la camara nunca funciona dentro del programa
("Cannot read properties of undefined (reading 'getUserMedia')"). Cargando la pagina
desde `http://localhost:<puerto>` en cambio, WebView2 la trata como contexto seguro sin
necesitar ningun certificado.

Solo hace falta reenviar HTTP normal (la pagina, su CSS/JS, y el POST /api/offer que
negocia la conexion): la transmision de video/audio en si va directo por WebRTC (ICE)
entre este PC y el servidor, no pasa por este proxy.
"""
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def iniciar_proxy_local(origen_remoto: str) -> str:
    """Levanta el proxy en un hilo de fondo y devuelve su base URL local
    (`http://localhost:<puerto>`), lista para anteponerle la misma ruta que se usaria
    contra el servidor real.
    """
    origen = urlparse(origen_remoto)
    base_remota = f"{origen.scheme}://{origen.netloc}"
    puerto_local = _puerto_libre()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass  # silencia el log de cada request en la consola

        def _reenviar(self, metodo: str) -> None:
            url_remota = base_remota + self.path
            cuerpo = None
            if metodo == "POST":
                largo = int(self.headers.get("Content-Length", 0))
                cuerpo = self.rfile.read(largo) if largo else None

            peticion = urllib.request.Request(url_remota, data=cuerpo, method=metodo)
            if self.headers.get("Content-Type"):
                peticion.add_header("Content-Type", self.headers["Content-Type"])

            try:
                with urllib.request.urlopen(peticion, timeout=15) as resp:
                    self._responder(resp.status, resp.getheaders(), resp.read())
            except urllib.error.HTTPError as err:
                self._responder(err.code, err.headers.items() if err.headers else [], err.read())
            except Exception:
                self.send_response(502)
                self.end_headers()

        def _responder(self, status: int, headers, cuerpo: bytes) -> None:
            self.send_response(status)
            for clave, valor in headers:
                if clave.lower() not in ("connection", "transfer-encoding"):
                    self.send_header(clave, valor)
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self) -> None:
            self._reenviar("GET")

        def do_POST(self) -> None:
            self._reenviar("POST")

    servidor = ThreadingHTTPServer(("127.0.0.1", puerto_local), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()

    return f"http://localhost:{puerto_local}"
