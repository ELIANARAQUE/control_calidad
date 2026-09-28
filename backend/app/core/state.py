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
    sede: Optional[str] = None
    modulo: Optional[str] = None
    conectado_desde: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    peer_connection: object = None  # RTCPeerConnection, tipado como object para evitar import circular
    ultimo_snapshot_jpeg: Optional[bytes] = None
    # Hora (ISO) de la fila 'conexion' de esta sesion en eventos_conexion.
    sesion_inicio: Optional[str] = None
    # Pausa en curso (almuerzo o break): {"id", "tipo", "inicio"}. Mientras exista, los loops de
    # video y audio no analizan nada (ni alertas, ni transcripcion, ni emociones).
    pausa: Optional[dict] = None


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

    def obtener(self, estacion_id: str) -> Optional[EstacionInfo]:
        return self._estaciones.get(estacion_id)

    def listar(self) -> list[EstacionInfo]:
        return list(self._estaciones.values())

    def actualizar_snapshot(self, estacion_id: str, jpeg_bytes: bytes) -> None:
        info = self._estaciones.get(estacion_id)
        if info is not None:
            info.ultimo_snapshot_jpeg = jpeg_bytes


class ConfigTiempoReal:
    """Ajustes que el supervisor puede cambiar en caliente, sin reiniciar el servidor."""

    def __init__(self) -> None:
        self.sensibilidad_lenguaje: str = "estricto"  # "estricto" | "moderado"


class NotificadorEstaciones:
    """Difunde mensajes del supervisor (ej. avisos) a todas las estaciones de empleado conectadas."""

    def __init__(self) -> None:
        self._estaciones_ws: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def conectar(self, ws: WebSocket) -> None:
        async with self._lock:
            self._estaciones_ws.add(ws)

    async def desconectar(self, ws: WebSocket) -> None:
        async with self._lock:
            self._estaciones_ws.discard(ws)

    async def difundir(self, mensaje: str) -> int:
        payload = {"tipo": "notificacion", "mensaje": mensaje, "timestamp": datetime.now(timezone.utc).isoformat()}
        enviados = 0
        muertos = []
        for ws in list(self._estaciones_ws):
            try:
                await ws.send_json(payload)
                enviados += 1
            except Exception:
                muertos.append(ws)
        for ws in muertos:
            await self.desconectar(ws)
        return enviados


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
config_tiempo_real = ConfigTiempoReal()
notificador_estaciones = NotificadorEstaciones()


def nuevo_evento(estacion_id: str, tipo: str, payload: dict) -> dict:
    return {
        "estacion_id": estacion_id,
        "tipo": tipo,  # "alerta_postura" | "transcripcion" | "conexion" | "desconexion"
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
