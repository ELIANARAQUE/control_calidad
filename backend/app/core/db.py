"""Persistencia en Supabase (Postgres) de todo lo que antes solo se transmitia en vivo por
WebSocket: alertas (con su veredicto), transcripciones y conexiones/desconexiones de
estaciones -mas las opciones configurables de sede/modulo-.

Antes esto vivia en un archivo SQLite local (`data/eventos.db`); se migro por completo a
Supabase (ver `supabase_schema.sql` para el esquema). Las fotos de las alertas (`captura_path`)
siguen guardandose en disco local en `RUTA_CAPTURAS` -son archivos binarios, no filas de base
de datos, y no hacia falta moverlos para este cambio-.

Cada funcion publica de este modulo es `async` y corre la consulta real a Supabase en un
thread-pool (ver `app.core.supabase_client.en_hilo`): supabase-py es sincrono (HTTP bloqueante),
y el resto del backend es asyncio, asi que sin esto cada consulta congelaria el event loop
completo -el mismo problema, ya resuelto antes, de correr codigo bloqueante directo en una
corutina-.
"""
from datetime import datetime, timezone
from pathlib import Path

from app.core.supabase_client import en_hilo, obtener_supabase

RUTA_CAPTURAS = Path(__file__).parent.parent.parent / "data" / "capturas"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Alertas
# ============================================================================

def _registrar_alerta_sync(estacion_id: str, detalle: str, tipo: str, captura_path: str | None) -> int:
    fila = {
        "estacion_id": estacion_id,
        "tipo": tipo,
        "detalle": detalle,
        "timestamp": _ahora(),
        "veredicto": None,
        "captura_path": captura_path,
    }
    respuesta = obtener_supabase().table("alertas").insert(fila).execute()
    return respuesta.data[0]["id"]


async def registrar_alerta(estacion_id: str, detalle: str, tipo: str = "postura", captura_path: str | None = None) -> int:
    """Guarda una alerta recien generada y devuelve su id, para que el panel de supervisor
    pueda referenciarla al confirmarla o descartarla despues.

    `tipo`: 'postura' (heuristica retirada, solo queda en el historial viejo), 'lenguaje'
    (posible grosería/mal trato transcrito), 'expresion' (gesto facial negativo) o 'ausencia'
    (nadie frente a la camara por mucho tiempo). `captura_path` es la ruta (relativa a
    `RUTA_CAPTURAS`) de la foto guardada en el momento de la alerta, si se pudo capturar.
    """
    return await en_hilo(_registrar_alerta_sync, estacion_id, detalle, tipo, captura_path)


def _obtener_captura_path_sync(alerta_id: int) -> str | None:
    respuesta = obtener_supabase().table("alertas").select("captura_path").eq("id", alerta_id).limit(1).execute()
    if not respuesta.data:
        return None
    return respuesta.data[0]["captura_path"]


async def obtener_captura_path(alerta_id: int) -> str | None:
    return await en_hilo(_obtener_captura_path_sync, alerta_id)


def _actualizar_veredicto_sync(alerta_id: int, veredicto: str) -> bool:
    respuesta = obtener_supabase().table("alertas").update({"veredicto": veredicto}).eq("id", alerta_id).execute()
    return len(respuesta.data) > 0


async def actualizar_veredicto(alerta_id: int, veredicto: str) -> bool:
    """veredicto: 'confirmada' (fue real, valia la pena reportarlo) o 'falsa_alarma' (ruido/
    gesto normal). Devuelve False si el id no existe."""
    return await en_hilo(_actualizar_veredicto_sync, alerta_id, veredicto)


def _eliminar_alertas_por_tipo_sync(tipo: str) -> list[str]:
    supabase = obtener_supabase()
    filas = (
        supabase.table("alertas").select("captura_path").eq("tipo", tipo).not_.is_("captura_path", "null").execute()
    )
    rutas = [fila["captura_path"] for fila in filas.data]
    supabase.table("alertas").delete().eq("tipo", tipo).execute()
    return rutas


async def eliminar_alertas_por_tipo(tipo: str) -> list[str]:
    """Borra todas las alertas de un `tipo` dado (usado para limpiar las de 'postura' tras
    retirar esa heuristica por falsos positivos). Devuelve las rutas de captura que quedaron
    huerfanas, para que quien llama borre tambien esos archivos del disco si quiere."""
    return await en_hilo(_eliminar_alertas_por_tipo_sync, tipo)


def _eliminar_alerta_positiva_sync(alerta_id: int) -> tuple[bool, str | None]:
    supabase = obtener_supabase()
    fila = supabase.table("alertas").select("tipo, captura_path").eq("id", alerta_id).limit(1).execute().data
    if not fila or fila[0]["tipo"] != "expresion_positiva":
        return False, None
    supabase.table("alertas").delete().eq("id", alerta_id).execute()
    return True, fila[0]["captura_path"]


async def eliminar_alerta_positiva(alerta_id: int) -> tuple[bool, str | None]:
    """Las expresiones positivas no se califican (real/falsa): solo se pueden eliminar. Solo
    borra alertas de ese tipo -una alerta negativa nunca se puede eliminar por aqui-. Devuelve
    `(eliminada, captura_path)` para que quien llama borre tambien la foto del disco."""
    return await en_hilo(_eliminar_alerta_positiva_sync, alerta_id)


# ============================================================================
# Transcripciones
# ============================================================================

def _registrar_transcripcion_sync(estacion_id: str, texto: str) -> None:
    obtener_supabase().table("transcripciones").insert(
        {"estacion_id": estacion_id, "texto": texto, "timestamp": _ahora()}
    ).execute()


async def registrar_transcripcion(estacion_id: str, texto: str) -> None:
    await en_hilo(_registrar_transcripcion_sync, estacion_id, texto)


# ============================================================================
# Emociones (muestreo periodico de la emocion dominante, no solo alertas negativas)
# ============================================================================

def _registrar_emocion_sync(estacion_id: str, emocion: str, probabilidad: float) -> None:
    obtener_supabase().table("emociones").insert(
        {"estacion_id": estacion_id, "emocion": emocion, "probabilidad": round(float(probabilidad), 3), "timestamp": _ahora()}
    ).execute()


async def registrar_emocion(estacion_id: str, emocion: str, probabilidad: float) -> None:
    await en_hilo(_registrar_emocion_sync, estacion_id, emocion, probabilidad)


# ============================================================================
# Eventos de conexion (conexion/desconexion de estaciones)
# ============================================================================

def _registrar_evento_conexion_sync(
    estacion_id: str,
    empleado_nombre: str | None,
    tipo: str,
    sede: str | None,
    modulo: str | None,
    acepto_habeas_data: bool | None,
) -> None:
    obtener_supabase().table("eventos_conexion").insert(
        {
            "estacion_id": estacion_id,
            "empleado_nombre": empleado_nombre,
            "tipo": tipo,
            "timestamp": _ahora(),
            "sede": sede,
            "modulo": modulo,
            "acepto_habeas_data": acepto_habeas_data,
        }
    ).execute()


async def registrar_evento_conexion(
    estacion_id: str,
    empleado_nombre: str | None,
    tipo: str,
    sede: str | None = None,
    modulo: str | None = None,
    acepto_habeas_data: bool | None = None,
) -> None:
    """tipo: 'conexion' o 'desconexion' -- log de cuando cada estacion entro/salio.

    `acepto_habeas_data` queda registrado como evidencia de auditoria de que el empleado
    autorizo el tratamiento de datos (Ley 1581 de 2012) antes de iniciar el monitoreo.
    """
    await en_hilo(_registrar_evento_conexion_sync, estacion_id, empleado_nombre, tipo, sede, modulo, acepto_habeas_data)


# ============================================================================
# Opciones configurables (sede / modulo)
# ============================================================================

def _obtener_opciones_sync() -> dict[str, list[str]]:
    filas = (
        obtener_supabase()
        .table("opciones_configurables")
        .select("tipo, valor, orden")
        .order("tipo")
        .order("orden")
        .execute()
    )
    resultado: dict[str, list[str]] = {"sede": [], "modulo": []}
    for fila in filas.data:
        resultado.setdefault(fila["tipo"], []).append(fila["valor"])
    return resultado


async def obtener_opciones() -> dict[str, list[str]]:
    """Opciones de 'sede/modalidad' y 'modulo/ventanilla' que el empleado ve en su login,
    editables por el supervisor sin tocar codigo (ver POST /api/config/opciones)."""
    return await en_hilo(_obtener_opciones_sync)


def _guardar_opciones_sync(tipo: str, valores: list[str]) -> None:
    supabase = obtener_supabase()
    supabase.table("opciones_configurables").delete().eq("tipo", tipo).execute()
    filas = [
        {"tipo": tipo, "valor": valor.strip(), "orden": orden}
        for orden, valor in enumerate(valores)
        if valor.strip()
    ]
    if filas:
        supabase.table("opciones_configurables").insert(filas).execute()


async def guardar_opciones(tipo: str, valores: list[str]) -> None:
    """Reemplaza por completo la lista de un tipo ('sede' o 'modulo') -asi el supervisor puede
    agregar, borrar o reordenar simplemente mandando la lista final desde el panel."""
    await en_hilo(_guardar_opciones_sync, tipo, valores)


# ============================================================================
# Diccionario de lenguaje inapropiado (editable desde el panel de administrador)
# ============================================================================

def _obtener_diccionario_lenguaje_sync() -> list[dict]:
    return (
        obtener_supabase().table("lenguaje_inapropiado").select("termino, categoria").order("termino").execute()
    ).data


async def obtener_diccionario_lenguaje() -> list[dict]:
    return await en_hilo(_obtener_diccionario_lenguaje_sync)


def _guardar_diccionario_lenguaje_sync(categoria: str, terminos: list[str]) -> None:
    supabase = obtener_supabase()
    supabase.table("lenguaje_inapropiado").delete().eq("categoria", categoria).execute()
    filas, vistos = [], set()
    for termino in terminos:
        limpio = " ".join(termino.strip().lower().split())
        if limpio and limpio not in vistos:
            vistos.add(limpio)
            filas.append({"termino": limpio, "categoria": categoria})
    if filas:
        # upsert: si el termino ya existia en OTRA categoria, se mueve a esta.
        supabase.table("lenguaje_inapropiado").upsert(filas, on_conflict="termino").execute()


async def guardar_diccionario_lenguaje(categoria: str, terminos: list[str]) -> None:
    """Reemplaza por completo los terminos de una categoria (groseria_fuerte, groseria_leve,
    mal_trato), igual que el editor de sede/modulo."""
    await en_hilo(_guardar_diccionario_lenguaje_sync, categoria, terminos)


# ============================================================================
# Sesiones: reconstruccion de ventanas de tiempo por estacion
# ============================================================================

def _calcular_sesiones(filas_eventos: list[dict]) -> list[dict]:
    """Reconstruye las 'sesiones' reales (ventanas de tiempo) de cada estacion, a partir del
    log crudo de `eventos_conexion` (ya ordenado por estacion_id, timestamp).

    El mismo `estacion_id` (un navegador/PC) puede reutilizarse con nombres distintos con el
    tiempo -en las pruebas del sistema paso seguido: "sergio", luego "computadro c1", luego
    "prueba 3", etc., todos en la misma maquina-. Antes, el reporte de un trabajador tomaba
    TODA la actividad de cualquier estacion que ese nombre hubiera usado alguna vez, sin
    importar cuando: eso mezclaba alertas/fotos de una sesion de "sergio" con las de
    "computadro c1" si compartian estacion_id, aunque fueran personas/momentos distintos.

    Aqui cada 'conexion' abre una sesion que dura hasta el SIGUIENTE evento (conexion o
    desconexion) en esa misma estacion, o hasta ahora si es el ultimo evento registrado (sesion
    todavia abierta). Asi cada alerta/transcripcion se puede asignar a la sesion exacta en la
    que ocurrio, no solo a la estacion.
    """
    ahora = _ahora()
    sesiones: list[dict] = []
    por_estacion: dict[str, list[dict]] = {}
    for fila in filas_eventos:
        por_estacion.setdefault(fila["estacion_id"], []).append(fila)

    for estacion_id, eventos_estacion in por_estacion.items():
        eventos_estacion.sort(key=lambda f: f["timestamp"])
        for i, fila in enumerate(eventos_estacion):
            if fila["tipo"] != "conexion":
                continue
            fin = eventos_estacion[i + 1]["timestamp"] if i + 1 < len(eventos_estacion) else ahora
            sesiones.append(
                {
                    "estacion_id": estacion_id,
                    "nombre": (fila["empleado_nombre"] or "Sin identificar").strip() or "Sin identificar",
                    "sede": fila["sede"],
                    "modulo": fila["modulo"],
                    "inicio": fila["timestamp"],
                    "fin": fin,
                }
            )
    return sesiones


def _obtener_ultima_sesion_sync(estacion_id: str) -> dict | None:
    filas = (
        obtener_supabase()
        .table("eventos_conexion")
        .select("tipo, timestamp")
        .eq("estacion_id", estacion_id)
        .order("timestamp")
        .execute()
    ).data
    conexiones = [f for f in filas if f["tipo"] == "conexion"]
    if not conexiones:
        return None
    inicio = conexiones[-1]["timestamp"]
    desconexion_posterior = next(
        (f["timestamp"] for f in filas if f["tipo"] == "desconexion" and f["timestamp"] > inicio), None
    )
    return {"inicio": inicio, "fin": desconexion_posterior}


def _historial_conexiones_sync(nombre: str) -> list[dict]:
    filas = (
        obtener_supabase()
        .table("eventos_conexion")
        .select("estacion_id, empleado_nombre, tipo, timestamp, sede, modulo")
        .order("timestamp")
        .execute()
    ).data
    # El fin de una sesion solo es real si le siguio un evento; si es la ultima fila de su
    # estacion, sigue abierta ("En curso").
    ultimos_por_estacion: dict[str, str] = {}
    for fila in filas:
        ultimos_por_estacion[fila["estacion_id"]] = fila["timestamp"]
    sesiones = [s for s in _calcular_sesiones(filas) if s["nombre"] == nombre]
    resultado = [
        {
            "inicio": s["inicio"],
            "fin": None if s["inicio"] == ultimos_por_estacion.get(s["estacion_id"]) else s["fin"],
            "sede": s["sede"],
            "modulo": s["modulo"],
        }
        for s in sesiones
    ]
    resultado.sort(key=lambda s: s["inicio"], reverse=True)
    return resultado


async def historial_conexiones(nombre: str) -> list[dict]:
    """Sesiones de monitoreo de un empleado (inicio, fin, sede, modulo): lo que ve en su
    "Ver histórico" -sin fotos, alertas ni reportes, que son solo para el supervisor-."""
    return await en_hilo(_historial_conexiones_sync, nombre)


async def obtener_ultima_sesion(estacion_id: str) -> dict | None:
    """Inicio (y fin, si ya se desconecto) de la sesion mas reciente de una estacion, para que
    el centro de control de una sola estacion pueda mostrar solo la actividad de ahora y no
    mezclarla con sesiones viejas de dias/horas anteriores bajo el mismo estacion_id."""
    return await en_hilo(_obtener_ultima_sesion_sync, estacion_id)


# ============================================================================
# Eventos recientes (para reconstruir el feed del panel al cargar una pagina)
# ============================================================================

def _listar_eventos_recientes_sync(limite_por_tipo: int) -> list[dict]:
    supabase = obtener_supabase()
    filas_alertas = (
        supabase.table("alertas")
        .select("id, estacion_id, tipo, detalle, timestamp, veredicto, captura_path")
        .order("timestamp", desc=True)
        .limit(limite_por_tipo)
        .execute()
    ).data
    filas_transcripciones = (
        supabase.table("transcripciones")
        .select("estacion_id, texto, timestamp")
        .order("timestamp", desc=True)
        .limit(limite_por_tipo)
        .execute()
    ).data
    # Nombre de empleado mas reciente por estacion: sin esto, una estacion que ya se desconecto
    # (o cuyo evento de conexion salio del panel en vivo antes de navegar a otra pagina)
    # mostraba el UUID crudo de la estacion en vez del nombre de la persona.
    filas_conexion = (
        supabase.table("eventos_conexion")
        .select("estacion_id, empleado_nombre, timestamp")
        .eq("tipo", "conexion")
        .order("timestamp")
        .execute()
    ).data
    nombres_por_estacion: dict[str, str] = {}
    for fila in filas_conexion:  # ascendente: el ultimo que se procesa es el mas reciente
        nombres_por_estacion[fila["estacion_id"]] = fila["empleado_nombre"]

    eventos = []
    for fila in filas_alertas:
        eventos.append(
            {
                "estacion_id": fila["estacion_id"],
                "empleado": nombres_por_estacion.get(fila["estacion_id"]),
                "tipo": f"alerta_{fila['tipo']}",
                "timestamp": fila["timestamp"],
                "detalle": fila["detalle"],
                "alerta_id": fila["id"],
                "veredicto": fila["veredicto"],
                "captura_url": f"/api/alertas/{fila['id']}/captura.jpg" if fila["captura_path"] else None,
            }
        )
    for fila in filas_transcripciones:
        eventos.append(
            {
                "estacion_id": fila["estacion_id"],
                "empleado": nombres_por_estacion.get(fila["estacion_id"]),
                "tipo": "transcripcion",
                "timestamp": fila["timestamp"],
                "texto": fila["texto"],
            }
        )
    eventos.sort(key=lambda e: e["timestamp"])
    return eventos


async def listar_eventos_recientes(limite_por_tipo: int = 300) -> list[dict]:
    """Alertas y transcripciones recientes de TODAS las estaciones, en el mismo formato que
    `nuevo_evento`/`bus_alertas.emitir` producen en vivo. Existe para que el panel de
    supervisor pueda reconstruir su historial en memoria al cargar (o recargar, ej. al
    navegar entre paginas) sin depender de haber estado conectado por WebSocket desde antes."""
    return await en_hilo(_listar_eventos_recientes_sync, limite_por_tipo)


# ============================================================================
# Reportes por trabajador
# ============================================================================

def _listar_trabajadores_para_informe_sync() -> list[dict]:
    supabase = obtener_supabase()
    filas_eventos = (
        supabase.table("eventos_conexion")
        .select("estacion_id, empleado_nombre, tipo, timestamp, sede, modulo")
        .order("timestamp")
        .execute()
    ).data
    sesiones = _calcular_sesiones(filas_eventos)

    alertas = supabase.table("alertas").select("estacion_id, tipo, timestamp").execute().data
    transcripciones = supabase.table("transcripciones").select("estacion_id, timestamp").execute().data

    trabajadores: dict[str, dict] = {}
    for sesion in sesiones:
        info = trabajadores.setdefault(
            sesion["nombre"],
            {
                "nombre": sesion["nombre"],
                "sedes": set(),
                "modulos": set(),
                "primera_conexion": sesion["inicio"],
                "ultima_conexion": sesion["inicio"],
                "sesiones": 0,
                "alertas_postura": 0,
                "alertas_lenguaje": 0,
                "alertas_expresion": 0,
                "alertas_ausencia": 0,
                "transcripciones": 0,
            },
        )
        if sesion["sede"]:
            info["sedes"].add(sesion["sede"])
        if sesion["modulo"]:
            info["modulos"].add(sesion["modulo"])
        info["primera_conexion"] = min(info["primera_conexion"], sesion["inicio"])
        info["ultima_conexion"] = max(info["ultima_conexion"], sesion["inicio"])
        info["sesiones"] += 1

    sesiones_por_estacion: dict[str, list[dict]] = {}
    for sesion in sesiones:
        sesiones_por_estacion.setdefault(sesion["estacion_id"], []).append(sesion)

    def _sesion_de(estacion_id: str, timestamp: str) -> dict | None:
        for sesion in sesiones_por_estacion.get(estacion_id, []):
            if sesion["inicio"] <= timestamp < sesion["fin"]:
                return sesion
        return None

    for fila in alertas:
        sesion = _sesion_de(fila["estacion_id"], fila["timestamp"])
        if sesion is None or sesion["nombre"] not in trabajadores:
            continue
        clave = f"alertas_{fila['tipo']}"
        if clave in trabajadores[sesion["nombre"]]:
            trabajadores[sesion["nombre"]][clave] += 1

    for fila in transcripciones:
        sesion = _sesion_de(fila["estacion_id"], fila["timestamp"])
        if sesion is not None and sesion["nombre"] in trabajadores:
            trabajadores[sesion["nombre"]]["transcripciones"] += 1

    resultado = []
    for info in trabajadores.values():
        total_alertas = (
            info["alertas_postura"] + info["alertas_lenguaje"] + info["alertas_expresion"] + info["alertas_ausencia"]
        )
        resultado.append(
            {
                "nombre": info["nombre"],
                "sedes": sorted(info["sedes"]),
                "modulos": sorted(info["modulos"]),
                "primera_conexion": info["primera_conexion"],
                "ultima_conexion": info["ultima_conexion"],
                "sesiones": info["sesiones"],
                "total_alertas": total_alertas,
                "alertas_postura": info["alertas_postura"],
                "alertas_lenguaje": info["alertas_lenguaje"],
                "alertas_expresion": info["alertas_expresion"],
                "alertas_ausencia": info["alertas_ausencia"],
                "transcripciones": info["transcripciones"],
            }
        )
    resultado.sort(key=lambda t: t["ultima_conexion"] or "", reverse=True)
    return resultado


async def listar_trabajadores_para_informe() -> list[dict]:
    """Un resumen por trabajador (agrupado por nombre) para poblar la lista de 'Historial y
    Reportes': con cuantas sesiones, alertas y desde cuando tiene actividad registrada.

    Cada alerta/transcripcion se cuenta solo si cayo dentro de la ventana de tiempo de una
    sesion de ese nombre (ver `_calcular_sesiones`), no simplemente si paso alguna vez por la
    misma estacion -asi no se le suman a un trabajador alertas que en realidad son de otra
    persona que uso el mismo equipo antes o despues."""
    return await en_hilo(_listar_trabajadores_para_informe_sync)


def _obtener_datos_reporte_trabajador_sync(nombre: str) -> dict:
    supabase = obtener_supabase()
    filas_eventos = (
        supabase.table("eventos_conexion")
        .select("estacion_id, empleado_nombre, tipo, timestamp, sede, modulo")
        .order("timestamp")
        .execute()
    ).data
    sesiones_trabajador = [s for s in _calcular_sesiones(filas_eventos) if s["nombre"] == nombre]

    estaciones = sorted({s["estacion_id"] for s in sesiones_trabajador})
    alertas: list[dict] = []
    transcripciones: list[dict] = []
    emociones: list[dict] = []
    if estaciones:
        emociones = (
            supabase.table("emociones")
            .select("estacion_id, emocion, timestamp")
            .in_("estacion_id", estaciones)
            .execute()
        ).data
        alertas = (
            supabase.table("alertas")
            .select("estacion_id, tipo, detalle, timestamp, veredicto, captura_path")
            .in_("estacion_id", estaciones)
            .order("timestamp")
            .execute()
        ).data
        transcripciones = (
            supabase.table("transcripciones")
            .select("estacion_id, texto, timestamp")
            .in_("estacion_id", estaciones)
            .order("timestamp")
            .execute()
        ).data

    def _dentro_de_alguna_sesion(estacion_id: str, timestamp: str) -> bool:
        return any(
            s["estacion_id"] == estacion_id and s["inicio"] <= timestamp < s["fin"] for s in sesiones_trabajador
        )

    eventos: list[dict] = []
    for fila in alertas:
        if not _dentro_de_alguna_sesion(fila["estacion_id"], fila["timestamp"]):
            continue
        eventos.append(
            {
                "timestamp": fila["timestamp"],
                "categoria": f"Alerta de {fila['tipo']}",
                "detalle": fila["detalle"],
                "veredicto": fila["veredicto"] or "Sin revisar",
                "captura_path": fila["captura_path"],
            }
        )
    for fila in transcripciones:
        if not _dentro_de_alguna_sesion(fila["estacion_id"], fila["timestamp"]):
            continue
        eventos.append(
            {
                "timestamp": fila["timestamp"],
                "categoria": "Transcripción",
                "detalle": fila["texto"],
                "veredicto": "",
                "captura_path": None,
            }
        )
    eventos.sort(key=lambda e: e["timestamp"])

    sesiones_para_reporte = [
        {
            "estacion_id": s["estacion_id"],
            "tipo": "conexion",
            "timestamp": s["inicio"],
            "sede": s["sede"],
            "modulo": s["modulo"],
        }
        for s in sesiones_trabajador
    ]

    conteo_emociones: dict[str, int] = {}
    for fila in emociones:
        if _dentro_de_alguna_sesion(fila["estacion_id"], fila["timestamp"]):
            conteo_emociones[fila["emocion"]] = conteo_emociones.get(fila["emocion"], 0) + 1

    return {
        "nombre": nombre,
        "sesiones": sesiones_para_reporte,
        "eventos": eventos,
        "emociones": conteo_emociones,
    }


async def obtener_datos_reporte_trabajador(nombre: str) -> dict:
    """Todo lo necesario para armar el reporte .xlsx de un trabajador: sus sesiones (una por
    cada 'conexion' con ese nombre) y, para cada una, solo las alertas/transcripciones que
    cayeron DENTRO de esa ventana de tiempo -no toda la historia de la estacion que uso-, para
    que el reporte de una persona nunca incluya actividad de otra que compartio el mismo
    equipo en otro momento."""
    return await en_hilo(_obtener_datos_reporte_trabajador_sync, nombre)
