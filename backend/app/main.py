"""Punto de entrada de la aplicacion FastAPI.

Ejecutar con:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
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

app.include_router(signaling.router, prefix="/api", tags=["webrtc"])
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(alertas.router, prefix="/api", tags=["alertas"])
app.include_router(estaciones.router, prefix="/api", tags=["estaciones"])
app.include_router(supervisor.router, tags=["supervisor"])

# Sirve el frontend estatico (clientes de empleado y panel de supervisor)
app.mount("/empleado", StaticFiles(directory="../frontend/employee", html=True), name="empleado")
app.mount("/supervisor", StaticFiles(directory="../frontend/supervisor", html=True), name="supervisor-ui")


@app.get("/api/salud")
async def salud() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "max_estaciones_concurrentes": settings.max_estaciones_concurrentes,
    }
