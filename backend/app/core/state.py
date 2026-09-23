"""Estado compartido en memoria: conexiones activas y difusion de alertas al panel de supervisor.

Para 12-15 empleados un simple registro en memoria es suficiente (no se requiere Redis/DB).
Si el proyecto crece a multiples servidores, reemplazar por un pub/sub externo.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket


@dataclass
class EstacionInfo:
    estacion_id: str
    empleado_nombre: str
    conectado_desde: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    peer_connection: object = None  # RTCPeerConnection, tipado como object para evitar import circular


class GestorEstaciones:
    """Lleva el registro de estaciones (empleados) conectadas via WebRTC."""

    def __init__(self) -> None:
        self._estaciones: dict[str, EstacionInfo] = {}
        self._lock = asyncio.Lock()

    async def registrar(self, info: EstacionInfo) -> bool:
        async with self._lock:
            from app.core.config import settings
            if len(self._estaciones) >= settings.max_estaciones_concurrentes:
                return False
            self._estaciones[info.estacion_id] = info
            return True

    async def liberar(self, estacion_id: str) -> None:
        async with self._lock:
            self._estaciones.pop(estacion_id, None)

    def activas(self) -> int:
        return len(self._estaciones)


class BusAlertas:
    """Difunde alertas y transcripciones en vivo a todos los supervisores conectados por WebSocket."""

    def __init__(self) -> None:
        self._supervisores: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def conectar_supervisor(self, ws: WebSocket) -> None:
        async with self._lock:
            self._supervisores.add(ws)

    async def desconectar_supervisor(self, ws: WebSocket) -> None:
        async with self._lock:
            self._supervisores.discard(ws)

    async def emitir(self, evento: dict) -> None:
        """Envia un evento (alerta o transcripcion) a todos los supervisores conectados."""
        muertos = []
        for ws in list(self._supervisores):
            try:
                await ws.send_json(evento)
            except Exception:
                muertos.append(ws)
        for ws in muertos:
            await self.desconectar_supervisor(ws)


gestor_estaciones = GestorEstaciones()
bus_alertas = BusAlertas()


def nuevo_evento(estacion_id: str, tipo: str, payload: dict) -> dict:
    return {
        "estacion_id": estacion_id,
        "tipo": tipo,  # "alerta_postura" | "transcripcion" | "conexion" | "desconexion"
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
