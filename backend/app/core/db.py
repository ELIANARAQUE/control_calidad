"""Persistencia en Postgres (Railway) de todo lo que antes solo se transmitia en vivo por
WebSocket: alertas (con su veredicto), transcripciones y conexiones/desconexiones de
estaciones -mas las opciones configurables de sede/modulo-.

Antes esto vivia en un archivo SQLite local (`data/eventos.db`), despues en Supabase (ver
`supabase_schema.sql`), y ahora en un Postgres nativo de Railway (ver
`backend/postgres_schema.sql` para el esquema, ya identico al de Supabase salvo el bucket
de Storage). Las fotos de las alertas (`captura_path`) siguen guardandose en disco local en
`RUTA_CAPTURAS` -son archivos binarios, no filas de base de datos, y no hacia falta
moverlos para este cambio-.

Cada funcion publica de este modulo es `async` y corre la consulta real a Postgres en un
thread-pool (ver `app.core.db_client.en_hilo`): psycopg3, en su modo sincrono, bloquea el
hilo mientras dura el round-trip, y el resto del backend es asyncio, asi que sin esto cada
consulta congelaria el event loop completo -el mismo problema, ya resuelto antes, de correr
codigo bloqueante directo en una corutina-.

Todo el SQL de aqui va parametrizado (`%s` / placeholders de psycopg): ningun valor que
venga de fuera (estacion_id, nombre, tipo, categoria, fechas, etc.) se concatena nunca
directo en el string del query -eso es lo que evita la inyeccion SQL-. Los unicos lugares
donde se arma el string con datos "propios" son nombres de tabla/columna fijos del codigo
(nunca valores de usuario), lo cual es seguro.
"""
from datetime import datetime, timezone
from pathlib import Path

from app.core.db_client import ejecutar, ejecutar_muchos, en_hilo

RUTA_CAPTURAS = Path(__file__).parent.parent.parent / "data" / "capturas"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _a_datetime(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _en_rango(iso: str, desde: datetime | None, hasta: datetime | None) -> bool:
    """El instante `iso` cae dentro de [desde, hasta) (cualquiera de los dos puede faltar)."""
    if desde is None and hasta is None:
        return True
    dt = _a_datetime(iso)
    return (desde is None or dt >= desde) and (hasta is None or dt < hasta)


def _sesion_en_rango(sesion: dict, desde: datetime | None, hasta: datetime | None) -> bool:
    """La sesion se cruza con el periodo [desde, hasta) aunque haya empezado antes o terminado despues."""
    return (hasta is None or _a_datetime(sesion["inicio"]) < hasta) and (
        desde is None or _a_datetime(sesion["fin"]) >= desde
    )


# ============================================================================
# Alertas
# ============================================================================

def _registrar_alerta_sync(estacion_id: str, detalle: str, tipo: str, captura_path: str | None) -> int:
    filas = ejecutar(
        """
        INSERT INTO alertas (estacion_id, tipo, detalle, timestamp, veredicto, captura_path)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (estacion_id, tipo, detalle, _ahora(), None, captura_path),
    )
    return filas[0]["id"]


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
    filas = ejecutar("SELECT captura_path FROM alertas WHERE id = %s LIMIT 1", (alerta_id,))
    if not filas:
        return None
    return filas[0]["captura_path"]


async def obtener_captura_path(alerta_id: int) -> str | None:
    return await en_hilo(_obtener_captura_path_sync, alerta_id)


def _actualizar_veredicto_sync(alerta_id: int, veredicto: str) -> bool:
    filas = ejecutar(
        "UPDATE alertas SET veredicto = %s WHERE id = %s RETURNING id",
        (veredicto, alerta_id),
    )
    return len(filas) > 0


async def actualizar_veredicto(alerta_id: int, veredicto: str) -> bool:
    """veredicto: 'confirmada' (fue real, valia la pena reportarlo) o 'falsa_alarma' (ruido/
    gesto normal). Devuelve False si el id no existe."""
    return await en_hilo(_actualizar_veredicto_sync, alerta_id, veredicto)


def _eliminar_alertas_por_tipo_sync(tipo: str) -> list[str]:
    filas = ejecutar(
        "SELECT captura_path FROM alertas WHERE tipo = %s AND captura_path IS NOT NULL",
        (tipo,),
    )
    rutas = [fila["captura_path"] for fila in filas]
    ejecutar("DELETE FROM alertas WHERE tipo = %s", (tipo,))
    return rutas


async def eliminar_alertas_por_tipo(tipo: str) -> list[str]:
    """Borra todas las alertas de un `tipo` dado (usado para limpiar las de 'postura' tras
    retirar esa heuristica por falsos positivos). Devuelve las rutas de captura que quedaron
    huerfanas, para que quien llama borre tambien esos archivos del disco si quiere."""
    return await en_hilo(_eliminar_alertas_por_tipo_sync, tipo)


def _eliminar_alerta_positiva_sync(alerta_id: int) -> tuple[bool, str | None]:
    filas = ejecutar("SELECT tipo, captura_path FROM alertas WHERE id = %s LIMIT 1", (alerta_id,))
    if not filas or filas[0]["tipo"] != "expresion_positiva":
        return False, None
    ejecutar("DELETE FROM alertas WHERE id = %s", (alerta_id,))
    return True, filas[0]["captura_path"]


async def eliminar_alerta_positiva(alerta_id: int) -> tuple[bool, str | None]:
    """Las expresiones positivas no se califican (real/falsa): solo se pueden eliminar. Solo
    borra alertas de ese tipo -una alerta negativa nunca se puede eliminar por aqui-. Devuelve
    `(eliminada, captura_path)` para que quien llama borre tambien la foto del disco."""
    return await en_hilo(_eliminar_alerta_positiva_sync, alerta_id)


# ============================================================================
# Transcripciones
# ============================================================================

def _registrar_transcripcion_sync(estacion_id: str, texto: str) -> None:
    ejecutar(
        "INSERT INTO transcripciones (estacion_id, texto, timestamp) VALUES (%s, %s, %s)",
        (estacion_id, texto, _ahora()),
    )


async def registrar_transcripcion(estacion_id: str, texto: str) -> None:
    await en_hilo(_registrar_transcripcion_sync, estacion_id, texto)


# ============================================================================
# Emociones (muestreo periodico de la emocion dominante, no solo alertas negativas)
# ============================================================================

def _registrar_emocion_sync(estacion_id: str, emocion: str, probabilidad: float) -> None:
    ejecutar(
        "INSERT INTO emociones (estacion_id, emocion, probabilidad, timestamp) VALUES (%s, %s, %s, %s)",
        (estacion_id, emocion, round(float(probabilidad), 3), _ahora()),
    )


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
) -> str:
    momento = _ahora()
    ejecutar(
        """
        INSERT INTO eventos_conexion
            (estacion_id, empleado_nombre, tipo, timestamp, sede, modulo, acepto_habeas_data)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (estacion_id, empleado_nombre, tipo, momento, sede, modulo, acepto_habeas_data),
    )
    return momento


async def registrar_evento_conexion(
    estacion_id: str,
    empleado_nombre: str | None,
    tipo: str,
    sede: str | None = None,
    modulo: str | None = None,
    acepto_habeas_data: bool | None = None,
) -> str:
    """tipo: 'conexion' o 'desconexion' -- log de cuando cada estacion entro/salio. Devuelve la
    hora registrada (la de 'conexion' identifica la sesion, ej. para sus pausas).

    `acepto_habeas_data` queda registrado como evidencia de auditoria de que el empleado
    autorizo el tratamiento de datos (Ley 1581 de 2012) antes de iniciar el monitoreo.
    """
    return await en_hilo(_registrar_evento_conexion_sync, estacion_id, empleado_nombre, tipo, sede, modulo, acepto_habeas_data)


# ============================================================================
# Pausas (almuerzo / break): una fila por cada vez que el empleado pausa la transmision
# ============================================================================

TIPOS_PAUSA = ("almuerzo", "break")


class ErrorPausas(Exception):
    """Con Supabase, la tabla `pausas` podia faltar en instalaciones viejas que no habian
    corrido el script SQL actualizado (PostgREST devolvia el error 'PGRST205'). Con Postgres
    nativo eso ya no puede pasar: `postgres_schema.sql` se aplica completo ANTES del primer
    deploy, asi que esta excepcion nunca se lanza -queda solo para que `app.api.estaciones`
    (que la importa y la captura) siga compilando sin tocar ese archivo en esta fase."""


def _iniciar_pausa_sync(estacion_id: str, empleado_nombre: str, sesion_inicio: str, tipo: str) -> dict:
    inicio = _ahora()
    filas = ejecutar(
        """
        INSERT INTO pausas (estacion_id, empleado_nombre, sesion_inicio, tipo, inicio)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (estacion_id, empleado_nombre, sesion_inicio, tipo, inicio),
    )
    return {"id": filas[0]["id"], "tipo": tipo, "inicio": inicio}


async def iniciar_pausa(estacion_id: str, empleado_nombre: str, sesion_inicio: str, tipo: str) -> dict:
    return await en_hilo(_iniciar_pausa_sync, estacion_id, empleado_nombre, sesion_inicio, tipo)


def _finalizar_pausas_abiertas_sync(estacion_id: str) -> None:
    ejecutar(
        "UPDATE pausas SET fin = %s WHERE estacion_id = %s AND fin IS NULL",
        (_ahora(), estacion_id),
    )


async def finalizar_pausas_abiertas(estacion_id: str) -> None:
    """Cierra la pausa abierta de la estacion (al reanudar, o si se desconecta estando en pausa)."""
    await en_hilo(_finalizar_pausas_abiertas_sync, estacion_id)


def _repartir_pausas(sesiones_por_estacion: dict[str, list[dict]], pausas: list[dict]) -> None:
    """Asigna cada pausa a la sesion en la que empezo y suma, por sesion, el tiempo total y las
    veces de cada tipo (una pausa sin `fin` cuenta hasta el fin de su sesion o hasta ahora)."""
    for sesiones in sesiones_por_estacion.values():
        for s in sesiones:
            s.setdefault("pausas", [])
    for fila in pausas:
        for s in sesiones_por_estacion.get(fila["estacion_id"], []):
            if s["inicio"] <= fila["inicio"] < s["fin"]:
                fin = fila["fin"] or min(s["fin"], _ahora())
                segundos = max(0, int((_a_datetime(fin) - _a_datetime(fila["inicio"])).total_seconds()))
                s["pausas"].append({"tipo": fila["tipo"], "inicio": fila["inicio"], "fin": fila["fin"], "segundos": segundos})
                break


def _totales_pausas(pausas: list[dict]) -> dict:
    totales = {}
    for tipo in TIPOS_PAUSA:
        del_tipo = [p for p in pausas if p["tipo"] == tipo]
        totales[f"veces_{tipo}"] = len(del_tipo)
        totales[f"segundos_{tipo}"] = sum(p["segundos"] for p in del_tipo)
    return totales


# ============================================================================
# Opciones configurables (sede / modulo)
# ============================================================================

def _obtener_opciones_sync() -> dict[str, list[str]]:
    filas = ejecutar("SELECT tipo, valor, orden FROM opciones_configurables ORDER BY tipo, orden")
    resultado: dict[str, list[str]] = {"sede": [], "modulo": []}
    for fila in filas:
        resultado.setdefault(fila["tipo"], []).append(fila["valor"])
    return resultado


async def obtener_opciones() -> dict[str, list[str]]:
    """Opciones de 'sede/modalidad' y 'modulo/ventanilla' que el empleado ve en su login,
    administradas por el supervisor desde el CRUD de "Historial y Reportes"."""
    return await en_hilo(_obtener_opciones_sync)


# CRUD por opcion (antes el panel reemplazaba la lista COMPLETA de golpe: guardar con el cuadro
# de texto vacio borraba todas las opciones). Las sesiones ya registradas guardan la sede y el
# modulo como TEXTO en `eventos_conexion`, asi que editar o eliminar una opcion solo afecta a
# las sesiones nuevas, nunca a los registros anteriores.

class ErrorOpcion(Exception):
    """Validacion del CRUD de opciones (vacia, duplicada, inexistente) -> 400/404 en la API."""


def _listar_opciones_detalle_sync() -> list[dict]:
    return ejecutar("SELECT id, tipo, valor, orden FROM opciones_configurables ORDER BY tipo, orden")


async def listar_opciones_detalle() -> list[dict]:
    return await en_hilo(_listar_opciones_detalle_sync)


def _existe_valor(tipo: str, valor: str, excepto_id: int | None = None) -> bool:
    filas = ejecutar("SELECT id, valor FROM opciones_configurables WHERE tipo = %s", (tipo,))
    return any(f["valor"].strip().lower() == valor.lower() and f["id"] != excepto_id for f in filas)


def _crear_opcion_sync(tipo: str, valor: str) -> dict:
    valor = " ".join(valor.split())
    if not valor:
        raise ErrorOpcion("El nombre de la opción no puede estar vacío")
    if _existe_valor(tipo, valor):
        raise ErrorOpcion(f'Ya existe la opción "{valor}"')
    siguiente_orden = ejecutar(
        "SELECT COALESCE(MAX(orden), -1) + 1 AS siguiente FROM opciones_configurables WHERE tipo = %s",
        (tipo,),
    )[0]["siguiente"]
    filas = ejecutar(
        """
        INSERT INTO opciones_configurables (tipo, valor, orden)
        VALUES (%s, %s, %s)
        RETURNING id, tipo, valor, orden
        """,
        (tipo, valor, siguiente_orden),
    )
    return filas[0]


async def crear_opcion(tipo: str, valor: str) -> dict:
    return await en_hilo(_crear_opcion_sync, tipo, valor)


def _editar_opcion_sync(opcion_id: int, valor: str) -> dict:
    valor = " ".join(valor.split())
    if not valor:
        raise ErrorOpcion("El nombre de la opción no puede estar vacío")
    actual = ejecutar("SELECT id, tipo FROM opciones_configurables WHERE id = %s", (opcion_id,))
    if not actual:
        raise LookupError("La opción no existe")
    if _existe_valor(actual[0]["tipo"], valor, excepto_id=opcion_id):
        raise ErrorOpcion(f'Ya existe la opción "{valor}"')
    filas = ejecutar(
        "UPDATE opciones_configurables SET valor = %s WHERE id = %s RETURNING id, tipo, valor, orden",
        (valor, opcion_id),
    )
    return filas[0]


async def editar_opcion(opcion_id: int, valor: str) -> dict:
    return await en_hilo(_editar_opcion_sync, opcion_id, valor)


def _eliminar_opcion_sync(opcion_id: int) -> bool:
    filas = ejecutar("DELETE FROM opciones_configurables WHERE id = %s RETURNING id", (opcion_id,))
    return len(filas) > 0


async def eliminar_opcion(opcion_id: int) -> bool:
    return await en_hilo(_eliminar_opcion_sync, opcion_id)


# ============================================================================
# Diccionario de lenguaje inapropiado (editable desde el panel de administrador)
# ============================================================================

def _obtener_diccionario_lenguaje_sync() -> list[dict]:
    return ejecutar("SELECT termino, categoria FROM lenguaje_inapropiado ORDER BY termino")


async def obtener_diccionario_lenguaje() -> list[dict]:
    return await en_hilo(_obtener_diccionario_lenguaje_sync)


def _guardar_diccionario_lenguaje_sync(categoria: str, terminos: list[str]) -> None:
    ejecutar("DELETE FROM lenguaje_inapropiado WHERE categoria = %s", (categoria,))
    filas, vistos = [], set()
    for termino in terminos:
        limpio = " ".join(termino.strip().lower().split())
        if limpio and limpio not in vistos:
            vistos.add(limpio)
            filas.append((limpio, categoria))
    if filas:
        # upsert: si el termino ya existia en OTRA categoria, se mueve a esta.
        ejecutar_muchos(
            """
            INSERT INTO lenguaje_inapropiado (termino, categoria)
            VALUES (%s, %s)
            ON CONFLICT (termino) DO UPDATE SET categoria = EXCLUDED.categoria
            """,
            filas,
        )


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
    filas = ejecutar(
        "SELECT tipo, timestamp FROM eventos_conexion WHERE estacion_id = %s ORDER BY timestamp",
        (estacion_id,),
    )
    conexiones = [f for f in filas if f["tipo"] == "conexion"]
    if not conexiones:
        return None
    inicio = conexiones[-1]["timestamp"]
    desconexion_posterior = next(
        (f["timestamp"] for f in filas if f["tipo"] == "desconexion" and f["timestamp"] > inicio), None
    )
    return {"inicio": inicio, "fin": desconexion_posterior}


def _historial_conexiones_sync(nombre: str) -> list[dict]:
    filas = ejecutar(
        "SELECT estacion_id, empleado_nombre, tipo, timestamp, sede, modulo FROM eventos_conexion ORDER BY timestamp"
    )
    # El fin de una sesion solo es real si le siguio un evento; si es la ultima fila de su
    # estacion, sigue abierta ("En curso").
    ultimos_por_estacion: dict[str, str] = {}
    for fila in filas:
        ultimos_por_estacion[fila["estacion_id"]] = fila["timestamp"]
    sesiones = [s for s in _calcular_sesiones(filas) if s["nombre"] == nombre]
    por_estacion: dict[str, list[dict]] = {}
    for s in sesiones:
        por_estacion.setdefault(s["estacion_id"], []).append(s)
    if por_estacion:
        pausas = ejecutar(
            "SELECT estacion_id, tipo, inicio, fin FROM pausas WHERE estacion_id = ANY(%s)",
            (list(por_estacion),),
        )
        _repartir_pausas(por_estacion, pausas)
    resultado = [
        {
            "inicio": s["inicio"],
            "fin": None if s["inicio"] == ultimos_por_estacion.get(s["estacion_id"]) else s["fin"],
            "sede": s["sede"],
            "modulo": s["modulo"],
            **_totales_pausas(s.get("pausas", [])),
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
    filas_alertas = ejecutar(
        """
        SELECT id, estacion_id, tipo, detalle, timestamp, veredicto, captura_path
        FROM alertas
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (limite_por_tipo,),
    )
    filas_transcripciones = ejecutar(
        """
        SELECT estacion_id, texto, timestamp
        FROM transcripciones
        ORDER BY timestamp DESC
        LIMIT %s
        """,
        (limite_por_tipo,),
    )
    # Nombre de empleado mas reciente por estacion: sin esto, una estacion que ya se desconecto
    # (o cuyo evento de conexion salio del panel en vivo antes de navegar a otra pagina)
    # mostraba el UUID crudo de la estacion en vez del nombre de la persona.
    filas_conexion = ejecutar(
        """
        SELECT estacion_id, empleado_nombre, timestamp
        FROM eventos_conexion
        WHERE tipo = 'conexion'
        ORDER BY timestamp
        """
    )
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
# Historial general: una fila por sesion de monitoreo (todos los empleados)
# ============================================================================

def _leer_tabla_ordenada(tabla: str, columnas: str) -> list[dict]:
    """Lee la tabla completa ordenada por timestamp. `tabla`/`columnas` son SIEMPRE
    constantes fijas del codigo (nunca valores de usuario) en cada uno de los llamados de
    este archivo, asi que armar el SQL con f-string aqui es seguro -muy distinto de
    interpolar un valor de fila, que siempre va parametrizado-.

    Con SQL crudo no existe el limite de 1000 filas por consulta que tenia PostgREST, asi
    que un solo SELECT alcanza y ya no hace falta paginar (antes: `_todas_las_filas`)."""
    return ejecutar(f"SELECT {columnas} FROM {tabla} ORDER BY timestamp")


def _listar_sesiones_historial_sync(desde: datetime | None, hasta: datetime | None, detalle: bool) -> list[dict]:
    filas_eventos = _leer_tabla_ordenada("eventos_conexion", "estacion_id, empleado_nombre, tipo, timestamp, sede, modulo")
    ultimos_por_estacion: dict[str, str] = {}
    for fila in filas_eventos:
        ultimos_por_estacion[fila["estacion_id"]] = fila["timestamp"]

    sesiones = [s for s in _calcular_sesiones(filas_eventos) if _sesion_en_rango(s, desde, hasta)]
    por_estacion: dict[str, list[dict]] = {}
    for sesion in sesiones:
        sesion["en_curso"] = sesion["inicio"] == ultimos_por_estacion.get(sesion["estacion_id"])
        sesion["alertas"] = []
        sesion["transcripciones"] = 0
        sesion["textos"] = []
        por_estacion.setdefault(sesion["estacion_id"], []).append(sesion)

    def _sesion_de(estacion_id: str, timestamp: str) -> dict | None:
        for sesion in por_estacion.get(estacion_id, []):
            if sesion["inicio"] <= timestamp < sesion["fin"]:
                return sesion
        return None

    pausas = ejecutar("SELECT estacion_id, tipo, inicio, fin FROM pausas ORDER BY inicio")
    _repartir_pausas(por_estacion, pausas)

    for fila in _leer_tabla_ordenada("alertas", "estacion_id, tipo, detalle, timestamp, veredicto, captura_path"):
        sesion = _sesion_de(fila["estacion_id"], fila["timestamp"])
        if sesion is not None:
            alerta = {
                "tipo": fila["tipo"],
                "detalle": fila["detalle"],
                "timestamp": fila["timestamp"],
                "veredicto": fila["veredicto"] or "sin_revisar",
            }
            if detalle:  # la ruta de la foto nunca sale al navegador, solo se usa en el Excel
                alerta["captura_path"] = fila["captura_path"]
            sesion["alertas"].append(alerta)
    columnas_transcripcion = "estacion_id, timestamp, texto" if detalle else "estacion_id, timestamp"
    for fila in _leer_tabla_ordenada("transcripciones", columnas_transcripcion):
        sesion = _sesion_de(fila["estacion_id"], fila["timestamp"])
        if sesion is not None:
            sesion["transcripciones"] += 1
            if detalle:
                sesion["textos"].append({"timestamp": fila["timestamp"], "texto": fila["texto"]})

    resultado = []
    for s in sesiones:
        fin = None if s["en_curso"] else s["fin"]
        duracion = int((_a_datetime(fin or _ahora()) - _a_datetime(s["inicio"])).total_seconds())
        totales_pausa = _totales_pausas(s["pausas"])
        segundos_pausa = totales_pausa["segundos_almuerzo"] + totales_pausa["segundos_break"]
        conteo = {t: 0 for t in ("lenguaje", "expresion", "ausencia", "expresion_positiva", "postura")}
        for alerta in s["alertas"]:
            if alerta["tipo"] in conteo:
                conteo[alerta["tipo"]] += 1
        resultado.append(
            {
                "id": f"{s['estacion_id']}|{s['inicio']}",
                "nombre": s["nombre"],
                "sede": s["sede"],
                "modulo": s["modulo"],
                "inicio": s["inicio"],
                "fin": fin,
                "duracion_segundos": duracion,
                # Tiempo de la sesion descontando almuerzos y breaks.
                "segundos_efectivos": max(0, duracion - segundos_pausa),
                **totales_pausa,
                "pausas": s["pausas"],
                "alertas_lenguaje": conteo["lenguaje"],
                "alertas_expresion": conteo["expresion"],
                "alertas_ausencia": conteo["ausencia"],
                "expresiones_positivas": conteo["expresion_positiva"],
                # Las expresiones positivas son informativas: no suman como alertas.
                "total_alertas": conteo["lenguaje"] + conteo["expresion"] + conteo["ausencia"] + conteo["postura"],
                "transcripciones": s["transcripciones"],
                "alertas": sorted(s["alertas"], key=lambda a: a["timestamp"]),
                **({"textos": s["textos"]} if detalle else {}),
            }
        )
    resultado.sort(key=lambda s: s["inicio"], reverse=True)
    return resultado


async def listar_sesiones_historial(
    desde: datetime | None = None, hasta: datetime | None = None, detalle: bool = False
) -> list[dict]:
    """TODAS las sesiones de monitoreo de todos los empleados (la mas reciente primero), con su
    hora de inicio y fin, y las alertas que ocurrieron dentro de cada una. `desde`/`hasta`
    (opcionales) dejan solo las sesiones que se cruzan con ese periodo. Con `detalle=True`
    cada sesion trae tambien sus transcripciones (`textos`) y la foto de cada alerta, para el
    Excel desglosado."""
    return await en_hilo(_listar_sesiones_historial_sync, desde, hasta, detalle)


# ============================================================================
# Reportes por trabajador
# ============================================================================

def _listar_trabajadores_para_informe_sync(desde: datetime | None, hasta: datetime | None) -> list[dict]:
    filas_eventos = ejecutar(
        "SELECT estacion_id, empleado_nombre, tipo, timestamp, sede, modulo FROM eventos_conexion ORDER BY timestamp"
    )
    sesiones = _calcular_sesiones(filas_eventos)

    alertas = ejecutar("SELECT estacion_id, tipo, timestamp FROM alertas")
    transcripciones = ejecutar("SELECT estacion_id, timestamp FROM transcripciones")

    trabajadores: dict[str, dict] = {}
    for sesion in sesiones:
        if not _sesion_en_rango(sesion, desde, hasta):
            continue
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
        if not _en_rango(fila["timestamp"], desde, hasta):
            continue
        sesion = _sesion_de(fila["estacion_id"], fila["timestamp"])
        if sesion is None or sesion["nombre"] not in trabajadores:
            continue
        clave = f"alertas_{fila['tipo']}"
        if clave in trabajadores[sesion["nombre"]]:
            trabajadores[sesion["nombre"]][clave] += 1

    for fila in transcripciones:
        if not _en_rango(fila["timestamp"], desde, hasta):
            continue
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


async def listar_trabajadores_para_informe(desde: datetime | None = None, hasta: datetime | None = None) -> list[dict]:
    """Un resumen por trabajador (agrupado por nombre) para poblar la lista de 'Historial y
    Reportes': con cuantas sesiones, alertas y desde cuando tiene actividad registrada.

    Cada alerta/transcripcion se cuenta solo si cayo dentro de la ventana de tiempo de una
    sesion de ese nombre (ver `_calcular_sesiones`), no simplemente si paso alguna vez por la
    misma estacion -asi no se le suman a un trabajador alertas que en realidad son de otra
    persona que uso el mismo equipo antes o despues.

    `desde`/`hasta` (opcionales) limitan el resumen a un periodo: solo cuentan las sesiones que
    se cruzan con el y las alertas/transcripciones ocurridas dentro."""
    return await en_hilo(_listar_trabajadores_para_informe_sync, desde, hasta)


def _obtener_datos_reporte_trabajador_sync(nombre: str, desde: datetime | None, hasta: datetime | None) -> dict:
    filas_eventos = ejecutar(
        "SELECT estacion_id, empleado_nombre, tipo, timestamp, sede, modulo FROM eventos_conexion ORDER BY timestamp"
    )
    sesiones_trabajador = [
        s for s in _calcular_sesiones(filas_eventos) if s["nombre"] == nombre and _sesion_en_rango(s, desde, hasta)
    ]

    estaciones = sorted({s["estacion_id"] for s in sesiones_trabajador})
    alertas: list[dict] = []
    transcripciones: list[dict] = []
    emociones: list[dict] = []
    if estaciones:
        emociones = ejecutar(
            "SELECT estacion_id, emocion, timestamp FROM emociones WHERE estacion_id = ANY(%s)",
            (estaciones,),
        )
        alertas = ejecutar(
            """
            SELECT estacion_id, tipo, detalle, timestamp, veredicto, captura_path
            FROM alertas
            WHERE estacion_id = ANY(%s)
            ORDER BY timestamp
            """,
            (estaciones,),
        )
        transcripciones = ejecutar(
            """
            SELECT estacion_id, texto, timestamp
            FROM transcripciones
            WHERE estacion_id = ANY(%s)
            ORDER BY timestamp
            """,
            (estaciones,),
        )

    def _dentro_de_alguna_sesion(estacion_id: str, timestamp: str) -> bool:
        if not _en_rango(timestamp, desde, hasta):
            return False
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


async def obtener_datos_reporte_trabajador(
    nombre: str, desde: datetime | None = None, hasta: datetime | None = None
) -> dict:
    """Todo lo necesario para armar el reporte .xlsx de un trabajador: sus sesiones (una por
    cada 'conexion' con ese nombre) y, para cada una, solo las alertas/transcripciones que
    cayeron DENTRO de esa ventana de tiempo -no toda la historia de la estacion que uso-, para
    que el reporte de una persona nunca incluya actividad de otra que compartio el mismo
    equipo en otro momento. `desde`/`hasta` (opcionales) limitan el reporte a un periodo."""
    return await en_hilo(_obtener_datos_reporte_trabajador_sync, nombre, desde, hasta)
