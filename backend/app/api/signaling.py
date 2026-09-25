"""Endpoint de senalizacion WebRTC: recibe el 'offer' SDP del cliente (empleado) y responde
con el 'answer', siguiendo el patron estandar de aiortc para servidores WebRTC en Python.
"""
import logging
import uuid

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.auth import info_de_token
from app.core.db import registrar_evento_conexion
from app.core.state import EstacionInfo, bus_alertas, gestor_estaciones, nuevo_evento
from app.services.webrtc.tracks import consumir_audio, consumir_video

logger = logging.getLogger(__name__)
router = APIRouter()

# Se mantienen referencias activas para que Python no las recolecte como basura
_peer_connections: set[RTCPeerConnection] = set()

# Necesario en cuanto la estacion de empleado deja de estar en la misma LAN que el servidor
# (ej. accediendo por un tunel/IP publica): sin un STUN, aiortc solo ofrece su IP privada
# como candidato ICE, que nadie fuera de la red local puede alcanzar. Si tras esto algunas
# redes muy restrictivas (NAT simetrico, firewalls corporativos estrictos) siguen sin poder
# transmitir video, el siguiente paso es montar un servidor TURN (ej. coturn) y agregarlo aqui.
_CONFIGURACION_ICE = RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")])


def _log_seccion_sdp(estacion_id: str, etiqueta: str, sdp: str, kind: str) -> None:
    """DEBUG temporal: imprime solo el bloque `m=<kind> ...` de un SDP (hasta el siguiente
    `m=` o el final), para no llenar el log con el SDP completo."""
    lineas = sdp.splitlines()
    bloque: list[str] = []
    dentro = False
    for linea in lineas:
        if linea.startswith(f"m={kind}"):
            dentro = True
        elif linea.startswith("m=") and dentro:
            break
        if dentro:
            bloque.append(linea)
    logger.info("[debug-sdp] estacion %s: %s -> %s", estacion_id, etiqueta, "\n".join(bloque) or "(no tiene seccion de %s)" % kind)


class OfertaWebRTC(BaseModel):
    sdp: str
    type: str
    token: str  # sesion de la cuenta autenticada (ver /auth/verificar-rostro): de ahi sale el nombre real
    estacion_id: str | None = None
    sede: str | None = None
    modulo: str | None = None
    acepto_habeas_data: bool = False


class RespuestaWebRTC(BaseModel):
    sdp: str
    type: str
    estacion_id: str


@router.post("/offer", response_model=RespuestaWebRTC)
async def recibir_oferta(oferta: OfertaWebRTC) -> RespuestaWebRTC:
    """Cada estacion de empleado llama a este endpoint una vez al iniciar su sesion."""
    sesion = info_de_token(oferta.token)
    if sesion is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada, vuelve a iniciar sesión")

    if not oferta.acepto_habeas_data:
        raise HTTPException(
            status_code=400,
            detail="Debe aceptar el aviso de tratamiento de datos (Ley 1581 de 2012) antes de iniciar el monitoreo",
        )

    # El nombre viene de la cuenta autenticada (login + verificacion facial), no de un campo de
    # texto libre que el navegador podia mandar antes -asi tampoco alguien puede escribir el
    # nombre de otra persona y hacerse pasar por ella en el monitoreo.
    empleado_nombre = sesion["nombre"]
    estacion_id = oferta.estacion_id or str(uuid.uuid4())

    info = EstacionInfo(
        estacion_id=estacion_id,
        empleado_nombre=empleado_nombre,
        sede=oferta.sede,
        modulo=oferta.modulo,
    )
    admitido = await gestor_estaciones.registrar(info)
    if not admitido:
        raise HTTPException(status_code=503, detail="Capacidad maxima de estaciones concurrentes alcanzada")

    pc = RTCPeerConnection(configuration=_CONFIGURACION_ICE)
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
            await registrar_evento_conexion(estacion_id, empleado_nombre, "desconexion")
            await bus_alertas.emitir(nuevo_evento(estacion_id, "desconexion", {"empleado": empleado_nombre}))

    @pc.on("track")
    def _on_track(track) -> None:
        logger.info("Track recibido de estacion %s: kind=%s", estacion_id, track.kind)
        if track.kind == "video":
            import asyncio
            asyncio.ensure_future(consumir_video(track, estacion_id))
        elif track.kind == "audio":
            import asyncio
            asyncio.ensure_future(consumir_audio(track, estacion_id))

    # DEBUG temporal: aisla justo la seccion de audio del SDP (offer del navegador y answer
    # del servidor) para ver si aiortc esta rechazando el audio en la negociacion (se veria
    # como "m=audio 0 ..." -puerto 0- en el answer) en vez de solo fallar en silencio despues.
    _log_seccion_sdp(estacion_id, "OFFER (navegador)", oferta.sdp, "audio")

    oferta_sdp = RTCSessionDescription(sdp=oferta.sdp, type=oferta.type)
    await pc.setRemoteDescription(oferta_sdp)

    respuesta = await pc.createAnswer()
    await pc.setLocalDescription(respuesta)

    _log_seccion_sdp(estacion_id, "ANSWER (servidor)", pc.localDescription.sdp, "audio")

    await registrar_evento_conexion(
        estacion_id,
        empleado_nombre,
        "conexion",
        sede=oferta.sede,
        modulo=oferta.modulo,
        acepto_habeas_data=oferta.acepto_habeas_data,
    )
    await bus_alertas.emitir(
        nuevo_evento(
            estacion_id,
            "conexion",
            {"empleado": empleado_nombre, "sede": oferta.sede, "modulo": oferta.modulo},
        )
    )

    return RespuestaWebRTC(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        estacion_id=estacion_id,
    )
