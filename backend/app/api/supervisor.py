"""WebSocket que alimenta el panel del supervisor con alertas y transcripciones en vivo."""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth import token_valido
from app.core.state import bus_alertas, gestor_estaciones

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/supervisor")
async def ws_supervisor(websocket: WebSocket) -> None:
    if not token_valido(websocket.query_params.get("token")):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await bus_alertas.conectar_supervisor(websocket)
    logger.info("Supervisor conectado. Estaciones activas: %d", gestor_estaciones.activas())

    try:
        while True:
            # No se espera contenido del cliente; se mantiene el socket vivo y se escucha
            # solo para detectar la desconexion.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await bus_alertas.desconectar_supervisor(websocket)
        logger.info("Supervisor desconectado")
