"""Endpoint de senalizacion WebRTC: recibe el 'offer' SDP del cliente (empleado) y responde
con el 'answer', siguiendo el patron estandar de aiortc para servidores WebRTC en Python.
"""
import logging
import uuid

from aiortc import RTCPeerConnection, RTCSessionDescription
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.db import registrar_evento_conexion
from app.core.state import EstacionInfo, bus_alertas, gestor_estaciones, nuevo_evento
from app.services.webrtc.tracks import consumir_audio, consumir_video

logger = logging.getLogger(__name__)
router = APIRouter()

# Se mantienen referencias activas para que Python no las recolecte como basura
_peer_connections: set[RTCPeerConnection] = set()


class OfertaWebRTC(BaseModel):
    sdp: str
    type: str
    empleado_nombre: str
    estacion_id: str | None = None


class RespuestaWebRTC(BaseModel):
    sdp: str
    type: str
    estacion_id: str


@router.post("/offer", response_model=RespuestaWebRTC)
async def recibir_oferta(oferta: OfertaWebRTC) -> RespuestaWebRTC:
    """Cada estacion de empleado llama a este endpoint una vez al iniciar su sesion."""
    estacion_id = oferta.estacion_id or str(uuid.uuid4())

    info = EstacionInfo(estacion_id=estacion_id, empleado_nombre=oferta.empleado_nombre)
    admitido = await gestor_estaciones.registrar(info)
    if not admitido:
        raise HTTPException(status_code=503, detail="Capacidad maxima de estaciones concurrentes alcanzada")

    pc = RTCPeerConnection()
    _peer_connections.add(pc)
    info.peer_connection = pc
    desconexion_ya_registrada = False

    @pc.on("connectionstatechange")
    async def _on_state_change() -> None:
        nonlocal desconexion_ya_registrada
        logger.info("Estacion %s -> estado conexion: %s", estacion_id, pc.connectionState)
        if pc.connectionState in ("failed", "closed", "disconnected") and not desconexion_ya_registrada:
            desconexion_ya_registrada = True  # el estado puede pasar por varios de estos seguidos
            await gestor_estaciones.liberar(estacion_id)
            _peer_connections.discard(pc)
            registrar_evento_conexion(estacion_id, oferta.empleado_nombre, "desconexion")
            await bus_alertas.emitir(nuevo_evento(estacion_id, "desconexion", {"empleado": oferta.empleado_nombre}))

    @pc.on("track")
    def _on_track(track) -> None:
        logger.info("Track recibido de estacion %s: kind=%s", estacion_id, track.kind)
        if track.kind == "video":
            import asyncio
            asyncio.ensure_future(consumir_video(track, estacion_id))
        elif track.kind == "audio":
            import asyncio
            asyncio.ensure_future(consumir_audio(track, estacion_id))

    oferta_sdp = RTCSessionDescription(sdp=oferta.sdp, type=oferta.type)
    await pc.setRemoteDescription(oferta_sdp)

    respuesta = await pc.createAnswer()
    await pc.setLocalDescription(respuesta)

    registrar_evento_conexion(estacion_id, oferta.empleado_nombre, "conexion")
    await bus_alertas.emitir(nuevo_evento(estacion_id, "conexion", {"empleado": oferta.empleado_nombre}))

    return RespuestaWebRTC(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        estacion_id=estacion_id,
    )
