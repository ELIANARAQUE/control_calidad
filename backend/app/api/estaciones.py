"""Endpoints de apoyo al panel de supervisor que no son ni senalizacion WebRTC ni alertas:
listado de estaciones activas, miniatura de video casi en vivo, notificaciones globales a las
estaciones de empleado, sensibilidad del filtro de lenguaje ajustable en caliente, y reportes
de evaluacion por trabajador.
"""
import logging
import urllib.parse
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.auth import requerir_admin, requerir_sesion
from app.core.db import (
    ErrorOpcion,
    TIPOS_PAUSA,
    ErrorPausas,
    crear_opcion,
    editar_opcion,
    finalizar_pausas_abiertas,
    iniciar_pausa,
    eliminar_opcion,
    guardar_diccionario_lenguaje,
    listar_opciones_detalle,
    historial_conexiones,
    obtener_diccionario_lenguaje,
    listar_eventos_recientes,
    listar_sesiones_historial,
    listar_trabajadores_para_informe,
    obtener_opciones,
    obtener_ultima_sesion,
)
from app.core.db_client import en_hilo
from app.core.state import bus_alertas, config_tiempo_real, gestor_estaciones, notificador_estaciones, nuevo_evento
from app.services.informes.historial import generar_historial_xlsx
from app.services.informes.reporte import generar_reporte_trabajador_xlsx
from app.services.stt.lenguaje import CATEGORIAS, NIVELES_SENSIBILIDAD, refrescar_diccionario

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config/opciones")
async def obtener_opciones_configurables() -> dict:
    """Publico (sin login): la estacion de empleado necesita esto para pintar los select de
    sede/modulo antes de que nadie haya iniciado sesion de supervisor."""
    return await obtener_opciones()


# --- CRUD de opciones de sede/modulo (solo admin) ---

@router.get("/config/opciones/detalle")
async def opciones_detalle(_admin: str = Depends(requerir_admin)) -> list[dict]:
    return await listar_opciones_detalle()


class NuevaOpcion(BaseModel):
    tipo: str
    valor: str


class EdicionOpcion(BaseModel):
    valor: str


@router.post("/config/opciones/items")
async def crear_opcion_endpoint(cuerpo: NuevaOpcion, _admin: str = Depends(requerir_admin)) -> dict:
    if cuerpo.tipo not in ("sede", "modulo"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'sede' o 'modulo'")
    try:
        return await crear_opcion(cuerpo.tipo, cuerpo.valor)
    except ErrorOpcion as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.put("/config/opciones/items/{opcion_id}")
async def editar_opcion_endpoint(opcion_id: int, cuerpo: EdicionOpcion, _admin: str = Depends(requerir_admin)) -> dict:
    try:
        return await editar_opcion(opcion_id, cuerpo.valor)
    except ErrorOpcion as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@router.delete("/config/opciones/items/{opcion_id}")
async def eliminar_opcion_endpoint(opcion_id: int, _admin: str = Depends(requerir_admin)) -> dict:
    if not await eliminar_opcion(opcion_id):
        raise HTTPException(status_code=404, detail="La opción no existe")
    return {"eliminada": opcion_id}


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
            "pausa": {"tipo": info.pausa["tipo"], "inicio": info.pausa["inicio"]} if info.pausa else None,
        }
        for info in gestor_estaciones.listar()
    ]


# --- Pausas de la transmision (almuerzo / break) ---

class Pausa(BaseModel):
    tipo: str


def _estacion_propia(estacion_id: str, sesion: dict):
    """La estacion debe estar transmitiendo y ser del empleado que hace la peticion."""
    info = gestor_estaciones.obtener(estacion_id)
    if info is None:
        raise HTTPException(status_code=404, detail="La estación no está transmitiendo")
    if sesion["rol"] != "admin" and info.empleado_nombre != sesion["nombre"]:
        raise HTTPException(status_code=403, detail="Esta estación no es de tu sesión")
    return info


@router.post("/estaciones/{estacion_id}/pausa")
async def pausar_estacion(estacion_id: str, cuerpo: Pausa, sesion: dict = Depends(requerir_sesion)) -> dict:
    """El empleado sale a almuerzo o a un break: se deja de analizar y de mostrar su video
    hasta que reanude. Cada pausa queda guardada en la tabla `pausas`."""
    if cuerpo.tipo not in TIPOS_PAUSA:
        raise HTTPException(status_code=400, detail=f"tipo debe ser uno de {list(TIPOS_PAUSA)}")
    info = _estacion_propia(estacion_id, sesion)
    if info.pausa:
        raise HTTPException(status_code=409, detail="La sesión ya está en pausa")
    if not info.sesion_inicio:
        raise HTTPException(status_code=409, detail="La sesión todavía se está iniciando, intenta de nuevo")
    try:
        info.pausa = await iniciar_pausa(estacion_id, info.empleado_nombre, info.sesion_inicio, cuerpo.tipo)
    except ErrorPausas as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    info.ultimo_snapshot_jpeg = None  # el panel deja de mostrar el ultimo cuadro
    await bus_alertas.emitir(
        nuevo_evento(estacion_id, "pausa", {"empleado": info.empleado_nombre, "tipo_pausa": cuerpo.tipo, "inicio": info.pausa["inicio"]})
    )
    return {"pausa": info.pausa}


@router.post("/estaciones/{estacion_id}/reanudar")
async def reanudar_estacion(estacion_id: str, sesion: dict = Depends(requerir_sesion)) -> dict:
    info = _estacion_propia(estacion_id, sesion)
    if not info.pausa:
        return {"reanudada": False}
    tipo = info.pausa["tipo"]
    info.pausa = None
    await finalizar_pausas_abiertas(estacion_id)
    await bus_alertas.emitir(nuevo_evento(estacion_id, "reanudacion", {"empleado": info.empleado_nombre, "tipo_pausa": tipo}))
    return {"reanudada": True}


@router.get("/config/lenguaje")
async def obtener_lenguaje(_admin: str = Depends(requerir_admin)) -> dict:
    """Diccionario de lenguaje inapropiado agrupado por categoria (para el editor del panel)."""
    filas = await obtener_diccionario_lenguaje()
    agrupado: dict[str, list[str]] = {c: [] for c in CATEGORIAS}
    for fila in filas:
        agrupado.setdefault(fila["categoria"], []).append(fila["termino"])
    return agrupado


class TerminosLenguaje(BaseModel):
    categoria: str
    terminos: list[str]


@router.post("/config/lenguaje")
async def actualizar_lenguaje(cuerpo: TerminosLenguaje, _admin: str = Depends(requerir_admin)) -> dict:
    if cuerpo.categoria not in CATEGORIAS:
        raise HTTPException(status_code=400, detail=f"categoria debe ser una de {list(CATEGORIAS)}")
    await guardar_diccionario_lenguaje(cuerpo.categoria, cuerpo.terminos)
    await refrescar_diccionario(forzar=True)  # los cambios aplican de inmediato
    return await obtener_lenguaje()


@router.get("/mis-sesiones")
async def mis_sesiones(sesion: dict = Depends(requerir_sesion)) -> list[dict]:
    """Historial de conexiones del empleado que inicio sesion (solo las suyas)."""
    return await historial_conexiones(sesion["nombre"])


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


_ZONA_COLOMBIA = ZoneInfo("America/Bogota")


def _periodo(desde: date | None, hasta: date | None) -> tuple[datetime | None, datetime | None]:
    """Fechas del filtro (dias calendario de Colombia, ambos incluidos) -> instantes [inicio, fin)."""
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=400, detail="La fecha 'desde' no puede ser posterior a la fecha 'hasta'")
    inicio = datetime.combine(desde, time.min, _ZONA_COLOMBIA) if desde else None
    fin = datetime.combine(hasta + timedelta(days=1), time.min, _ZONA_COLOMBIA) if hasta else None
    return inicio, fin


def _texto_periodo(desde: date | None, hasta: date | None) -> str:
    if not desde and not hasta:
        return "Todo el historial"
    formato = "%d/%m/%Y"
    if desde and hasta:
        return f"Del {desde.strftime(formato)} al {hasta.strftime(formato)}"
    return f"Desde el {desde.strftime(formato)}" if desde else f"Hasta el {hasta.strftime(formato)}"


@router.get("/informes/trabajadores")
async def listar_trabajadores(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    _admin: str = Depends(requerir_admin),
) -> list[dict]:
    """Un resumen por trabajador para la pagina 'Historial y Reportes' (opcionalmente solo de
    un periodo): de ahi el supervisor filtra, exporta o descarga el reporte individual."""
    return await listar_trabajadores_para_informe(*_periodo(desde, hasta))


@router.get("/informes/sesiones")
async def listar_sesiones(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    _admin: str = Depends(requerir_admin),
) -> list[dict]:
    """Historial general de 'Historial y Reportes': una fila por sesion de monitoreo de TODOS
    los empleados (inicio, fin, sede, modulo y sus alertas), opcionalmente de un periodo."""
    return await listar_sesiones_historial(*_periodo(desde, hasta))


class ExportarHistorial(BaseModel):
    desde: date | None = None
    hasta: date | None = None
    ids: list[str]  # sesiones a exportar: todo lo filtrado en pantalla o solo las marcadas
    descripcion: str = ""


@router.post("/informes/sesiones/reporte.xlsx")
async def exportar_historial_xlsx(cuerpo: ExportarHistorial, _admin: str = Depends(requerir_admin)) -> Response:
    """Excel desglosado del historial (Resumen, Sesiones, Alertas con foto y Transcripciones)."""
    pedidas = set(cuerpo.ids)
    sesiones = [
        s for s in await listar_sesiones_historial(*_periodo(cuerpo.desde, cuerpo.hasta), detalle=True) if s["id"] in pedidas
    ]
    descripcion = cuerpo.descripcion.strip()[:300] or _texto_periodo(cuerpo.desde, cuerpo.hasta)
    contenido = await en_hilo(generar_historial_xlsx, sesiones, descripcion)
    hoy = datetime.now(_ZONA_COLOMBIA).strftime("%Y-%m-%d")
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="historial_sesiones_{hoy}.xlsx"'},
    )


@router.get("/informes/trabajadores/{nombre}/reporte.xlsx")
async def reporte_trabajador_xlsx(
    nombre: str,
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    _admin: str = Depends(requerir_admin),
) -> Response:
    nombre_decodificado = urllib.parse.unquote(nombre)
    contenido = await generar_reporte_trabajador_xlsx(
        nombre_decodificado, *_periodo(desde, hasta), periodo=_texto_periodo(desde, hasta)
    )
    nombre_archivo = "".join(c if c.isalnum() or c in " _-" else "_" for c in nombre_decodificado).strip() or "trabajador"
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="reporte_{nombre_archivo}.xlsx"'},
    )
