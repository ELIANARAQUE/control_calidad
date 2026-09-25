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
from fastapi.staticfiles import StaticFiles

from app.api import alertas, auth, estaciones, signaling, supervisor
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

@app.middleware("http")
async def sin_cache_para_frontend(request, call_next):
    """Obliga al navegador a revalidar el HTML/JS del frontend en cada carga: sin esto, tras
    actualizar el sistema seguia sirviendose de cache la version vieja de la pagina (ej. la
    estacion de empleado con el campo "Nombre completo" y el /api/offer sin token -> 422)."""
    respuesta = await call_next(request)
    if not request.url.path.startswith("/api"):
        respuesta.headers["Cache-Control"] = "no-cache"
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


@app.get("/api/salud")
async def salud() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "max_estaciones_concurrentes": settings.max_estaciones_concurrentes,
    }
