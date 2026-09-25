"""Endpoints de apoyo al panel de supervisor que no son ni senalizacion WebRTC ni alertas:
listado de estaciones activas, miniatura de video casi en vivo, notificaciones globales a las
estaciones de empleado, sensibilidad del filtro de lenguaje ajustable en caliente, y reportes
de evaluacion por trabajador.
"""
import logging
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.auth import requerir_admin
from app.core.db import (
    guardar_opciones,
    listar_eventos_recientes,
    listar_trabajadores_para_informe,
    obtener_opciones,
    obtener_ultima_sesion,
)
from app.core.state import config_tiempo_real, gestor_estaciones, notificador_estaciones
from app.services.informes.reporte import generar_reporte_trabajador_xlsx
from app.services.stt.lenguaje import NIVELES_SENSIBILIDAD

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config/opciones")
async def obtener_opciones_configurables() -> dict:
    """Publico (sin login): la estacion de empleado necesita esto para pintar los select de
    sede/modulo antes de que nadie haya iniciado sesion de supervisor."""
    return await obtener_opciones()


class ListaOpciones(BaseModel):
    tipo: str
    valores: list[str]


@router.post("/config/opciones")
async def actualizar_opciones_configurables(cuerpo: ListaOpciones, _admin: str = Depends(requerir_admin)) -> dict:
    if cuerpo.tipo not in ("sede", "modulo"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'sede' o 'modulo'")
    await guardar_opciones(cuerpo.tipo, cuerpo.valores)
    return await obtener_opciones()


@router.get("/estaciones")
async def listar_estaciones(_admin: str = Depends(requerir_admin)) -> list[dict]:
    """Estaciones con una sesion WebRTC activa en este momento (para poblar el panel al
    abrirlo o refrescarlo, sin depender de haber estado conectado por WebSocket desde antes)."""
    return [
        {
            "estacion_id": info.estacion_id,
            "empleado_nombre": info.empleado_nombre,
            "sede": info.sede,
            "modulo": info.modulo,
            "conectado_desde": info.conectado_desde.isoformat(),
            "tiene_snapshot": info.ultimo_snapshot_jpeg is not None,
        }
        for info in gestor_estaciones.listar()
    ]


@router.get("/eventos/recientes")
async def eventos_recientes(_admin: str = Depends(requerir_admin)) -> list[dict]:
    """Historial reciente (alertas + transcripciones de todas las estaciones) para que el
    panel reconstruya su feed en memoria al cargar una pagina, sin depender de haber estado
    conectado por WebSocket desde antes."""
    return await listar_eventos_recientes()


@router.get("/estaciones/{estacion_id}/sesion")
async def sesion_estacion(estacion_id: str, _admin: str = Depends(requerir_admin)) -> dict:
    """Inicio (y fin, si aplica) de la sesion mas reciente de una estacion, para que el
    centro de control de una sola estacion pueda mostrar solo la actividad de ahora y no
    mezclarla con sesiones viejas de dias/horas anteriores bajo el mismo estacion_id."""
    sesion = await obtener_ultima_sesion(estacion_id)
    if sesion is None:
        raise HTTPException(status_code=404, detail="Esta estación no tiene sesiones registradas")
    return sesion


@router.get("/estaciones/{estacion_id}/snapshot.jpg")
async def snapshot_estacion(estacion_id: str, _admin: str = Depends(requerir_admin)) -> Response:
    info = gestor_estaciones.obtener(estacion_id)
    if info is None or info.ultimo_snapshot_jpeg is None:
        raise HTTPException(status_code=404, detail="Sin miniatura disponible todavia")
    return Response(content=info.ultimo_snapshot_jpeg, media_type="image/jpeg")


class Notificacion(BaseModel):
    mensaje: str


@router.post("/notificaciones")
async def enviar_notificacion(cuerpo: Notificacion, _admin: str = Depends(requerir_admin)) -> dict:
    mensaje = cuerpo.mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio")
    enviados = await notificador_estaciones.difundir(mensaje)
    return {"enviados": enviados}


@router.websocket("/ws/notificaciones")
async def ws_notificaciones(websocket: WebSocket) -> None:
    """Cada estacion de empleado se conecta aqui para recibir avisos del supervisor en vivo."""
    await websocket.accept()
    await notificador_estaciones.conectar(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await notificador_estaciones.desconectar(websocket)


class Sensibilidad(BaseModel):
    nivel: str


@router.get("/config/sensibilidad")
async def obtener_sensibilidad() -> dict:
    return {"nivel": config_tiempo_real.sensibilidad_lenguaje, "niveles_disponibles": list(NIVELES_SENSIBILIDAD)}


@router.post("/config/sensibilidad")
async def actualizar_sensibilidad(cuerpo: Sensibilidad, _admin: str = Depends(requerir_admin)) -> dict:
    if cuerpo.nivel not in NIVELES_SENSIBILIDAD:
        raise HTTPException(status_code=400, detail=f"nivel debe ser uno de {list(NIVELES_SENSIBILIDAD)}")
    config_tiempo_real.sensibilidad_lenguaje = cuerpo.nivel
    return {"nivel": config_tiempo_real.sensibilidad_lenguaje}


@router.get("/informes/trabajadores")
async def listar_trabajadores(_admin: str = Depends(requerir_admin)) -> list[dict]:
    """Un resumen por trabajador para la pagina 'Historial y Reportes': de ahi el supervisor
    elige a quien descargarle el reporte individual."""
    return await listar_trabajadores_para_informe()


@router.get("/informes/trabajadores/{nombre}/reporte.xlsx")
async def reporte_trabajador_xlsx(nombre: str, _admin: str = Depends(requerir_admin)) -> Response:
    nombre_decodificado = urllib.parse.unquote(nombre)
    contenido = await generar_reporte_trabajador_xlsx(nombre_decodificado)
    nombre_archivo = "".join(c if c.isalnum() or c in " _-" else "_" for c in nombre_decodificado).strip() or "trabajador"
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="reporte_{nombre_archivo}.xlsx"'},
    )
