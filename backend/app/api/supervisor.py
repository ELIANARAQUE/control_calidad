"""WebSocket que alimenta el panel del supervisor con alertas y transcripciones en vivo."""
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth import info_de_token
from app.core.state import bus_alertas, gestor_estaciones

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/supervisor")
async def ws_supervisor(websocket: WebSocket) -> None:
    # Este socket transmite en vivo alertas/transcripciones/video de TODOS los empleados: es
    # informacion exclusiva de supervisor, no basta con "cualquier sesion valida" (eso permitiria
    # que un empleado autenticado espiara a sus compañeros). Como en un WebSocket no aplica una
    # `Depends` de FastAPI igual que en un endpoint REST, se valida el token a mano y ademas se
    # exige rol admin -misma verificacion que hace `requerir_admin` para las rutas REST-.
    info = info_de_token(websocket.query_params.get("token"))
    if info is None:
        await websocket.close(code=4401)
        return
    if info["rol"] != "admin":
        await websocket.close(code=4403)
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
