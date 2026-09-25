"""Punto de entrada de la aplicacion FastAPI.

Ejecutar con:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import sys

# La consola de Windows por defecto usa cp1252, que no puede imprimir emojis -deepface (usado
# para el login facial) imprime una advertencia con "⚠️" apenas se importa, y sin esto el
# servidor se cae al arrancar con UnicodeEncodeError antes de levantar nada. Se fuerza UTF-8
# en stdout/stderr aqui, antes de cualquier otro import, para que ningun print con emoji o
# tilde tumbe el proceso sin importar que libreria lo escriba.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import alertas, auth, estaciones, signaling, supervisor
from app.core.auth import COOKIE_SESION, info_de_token
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(title=settings.app_name)

# En una red local cerrada esto es aceptable; restringir origenes si se expone mas alla de la LAN.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ROL_POR_HOME = {"/empleado": "empleado", "/supervisor": "admin"}
_HOME_POR_ROL = {"empleado": "/empleado/", "admin": "/supervisor/"}


@app.middleware("http")
async def sesion_y_sin_cache(request, call_next):
    """1) Nadie entra a /empleado/ ni a /supervisor/ sin haber iniciado sesion (cookie de
    sesion valida), y cada rol solo entra a su propio home -se valida en el SERVIDOR, antes de
    servir la pagina; el JavaScript no puede saltarse esto-.
    2) Obliga al navegador a revalidar el HTML/JS del frontend en cada carga, para que tras una
    actualizacion no siga mostrando una version vieja guardada en cache."""
    ruta = request.url.path
    home = next((h for h in _ROL_POR_HOME if ruta == h or ruta.startswith(h + "/")), None)
    if home is not None:
        sesion = info_de_token(request.cookies.get(COOKIE_SESION))
        if sesion is None:
            return RedirectResponse("/login/", status_code=303)
        if sesion["rol"] != _ROL_POR_HOME[home]:
            return RedirectResponse(_HOME_POR_ROL[sesion["rol"]], status_code=303)

    respuesta = await call_next(request)
    if not ruta.startswith("/api"):
        respuesta.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return respuesta


app.include_router(signaling.router, prefix="/api", tags=["webrtc"])
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(alertas.router, prefix="/api", tags=["alertas"])
app.include_router(estaciones.router, prefix="/api", tags=["estaciones"])
app.include_router(supervisor.router, tags=["supervisor"])

# Sirve el frontend estatico (clientes de empleado y panel de supervisor, mas el registro y el
# login unificado -compartidos por ambos roles-).
app.mount("/empleado", StaticFiles(directory="../frontend/employee", html=True), name="empleado")
app.mount("/supervisor", StaticFiles(directory="../frontend/supervisor", html=True), name="supervisor-ui")
app.mount("/registro", StaticFiles(directory="../frontend/registro", html=True), name="registro")
app.mount("/login", StaticFiles(directory="../frontend/login", html=True), name="login")


@app.get("/")
async def raiz() -> RedirectResponse:
    return RedirectResponse("/login/", status_code=303)


@app.get("/api/salud")
async def salud() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "max_estaciones_concurrentes": settings.max_estaciones_concurrentes,
    }
