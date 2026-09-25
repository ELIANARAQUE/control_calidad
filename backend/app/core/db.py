"""Persistencia en SQLite de todo lo que hoy solo se transmitia en vivo por WebSocket:
alertas (con su veredicto), transcripciones y conexiones/desconexiones de estaciones.

Antes, si nadie tenia el panel de supervisor abierto en el momento, esa informacion se
perdia -el `BusAlertas` solo reenvia a quien este conectado en ese instante-. Ahora queda
guardada para poder revisarla despues, y las alertas con veredicto son ademas el dataset
etiquetado que hace falta para, mas adelante, entrenar un modelo propio.

SQLite (no Postgres) porque el volumen -pocas alertas/transcripciones por estacion al dia,
12-15 estaciones- no justifica un motor de base de datos aparte.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

RUTA_DB = Path(__file__).parent.parent.parent / "data" / "eventos.db"
RUTA_CAPTURAS = Path(__file__).parent.parent.parent / "data" / "capturas"


@contextmanager
def _conexion():
    RUTA_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(RUTA_DB)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def inicializar_db() -> None:
    with _conexion() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estacion_id TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'postura',
                detalle TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                veredicto TEXT
            )
            """
        )
        # Migra bases de datos creadas antes de que existiera la columna "tipo"
        columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(alertas)")}
        if "tipo" not in columnas:
            conn.execute("ALTER TABLE alertas ADD COLUMN tipo TEXT NOT NULL DEFAULT 'postura'")
        if "captura_path" not in columnas:
            conn.execute("ALTER TABLE alertas ADD COLUMN captura_path TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estacion_id TEXT NOT NULL,
                texto TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eventos_conexion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estacion_id TEXT NOT NULL,
                empleado_nombre TEXT,
                tipo TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        # Migra bases de datos creadas antes de sede/modulo/habeas data
        columnas_conexion = {fila[1] for fila in conn.execute("PRAGMA table_info(eventos_conexion)")}
        if "sede" not in columnas_conexion:
            conn.execute("ALTER TABLE eventos_conexion ADD COLUMN sede TEXT")
        if "modulo" not in columnas_conexion:
            conn.execute("ALTER TABLE eventos_conexion ADD COLUMN modulo TEXT")
        if "acepto_habeas_data" not in columnas_conexion:
            conn.execute("ALTER TABLE eventos_conexion ADD COLUMN acepto_habeas_data INTEGER")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_alertas_estacion ON alertas(estacion_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transcripciones_estacion ON transcripciones(estacion_id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS opciones_configurables (
                tipo TEXT NOT NULL,
                valor TEXT NOT NULL,
                orden INTEGER NOT NULL,
                PRIMARY KEY (tipo, valor)
            )
            """
        )
        # Semillas: la primera vez que arranca el servidor, deja precargadas las mismas
        # opciones que antes estaban fijas en el HTML, para no dejarle a nadie el select vacio.
        hay_opciones = conn.execute("SELECT COUNT(*) FROM opciones_configurables").fetchone()[0]
        if hay_opciones == 0:
            semillas = [
                ("sede", "Sede Principal"),
                ("sede", "Campus Norte"),
                ("sede", "Atención Virtual"),
                ("modulo", "Admisiones y Registro"),
                ("modulo", "Financiera y Crédito"),
                ("modulo", "Soporte Técnico"),
                ("modulo", "Bienestar Universitario"),
            ]
            for orden, (tipo, valor) in enumerate(semillas):
                conn.execute(
                    "INSERT INTO opciones_configurables (tipo, valor, orden) VALUES (?, ?, ?)",
                    (tipo, valor, orden),
                )


def registrar_alerta(estacion_id: str, detalle: str, tipo: str = "postura", captura_path: str | None = None) -> int:
    """Guarda una alerta recien generada y devuelve su id, para que el panel de
    supervisor pueda referenciarla al confirmarla o descartarla despues.

    `tipo`: 'postura' (movimiento brusco), 'lenguaje' (posible grosería transcrita) o
    'expresion' (gesto facial negativo). `captura_path` es la ruta (relativa a
    `recordings_dir`) de la foto guardada en el momento de la alerta, si se pudo capturar.
    """
    with _conexion() as conn:
        cursor = conn.execute(
            "INSERT INTO alertas (estacion_id, tipo, detalle, timestamp, veredicto, captura_path) VALUES (?, ?, ?, ?, NULL, ?)",
            (estacion_id, tipo, detalle, datetime.now(timezone.utc).isoformat(), captura_path),
        )
        return cursor.lastrowid


def obtener_captura_path(alerta_id: int) -> str | None:
    with _conexion() as conn:
        fila = conn.execute("SELECT captura_path FROM alertas WHERE id = ?", (alerta_id,)).fetchone()
        return fila[0] if fila else None


def obtener_ultima_sesion(estacion_id: str) -> dict | None:
    """Inicio (y fin, si ya se desconecto) de la sesion mas reciente de una estacion, segun
    `eventos_conexion`. Existe para que el centro de control de una sola estacion pueda
    mostrar solo la actividad de la sesion actual/mas reciente -sin esto, si la misma
    computadora se reconecta varias veces en el dia (o en dias distintos) reusando el mismo
    `estacion_id`, se mezclaban alertas/transcripciones de sesiones viejas con las de ahora,
    lo que el supervisor via como "alertas de otra camara"."""
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        ultima_conexion = conn.execute(
            "SELECT timestamp FROM eventos_conexion WHERE estacion_id = ? AND tipo = 'conexion' "
            "ORDER BY timestamp DESC LIMIT 1",
            (estacion_id,),
        ).fetchone()
        if ultima_conexion is None:
            return None
        inicio = ultima_conexion["timestamp"]
        desconexion_posterior = conn.execute(
            "SELECT timestamp FROM eventos_conexion WHERE estacion_id = ? AND tipo = 'desconexion' "
            "AND timestamp > ? ORDER BY timestamp ASC LIMIT 1",
            (estacion_id, inicio),
        ).fetchone()
        return {"inicio": inicio, "fin": desconexion_posterior["timestamp"] if desconexion_posterior else None}


def listar_eventos_recientes(limite_por_tipo: int = 300) -> list[dict]:
    """Alertas y transcripciones recientes de TODAS las estaciones, en el mismo formato que
    `nuevo_evento`/`bus_alertas.emitir` producen en vivo. Existe para que el panel de
    supervisor pueda reconstruir su historial en memoria al cargar (o recargar, ej. al
    navegar entre paginas) sin depender de haber estado conectado por WebSocket desde antes
    -sin esto, cambiar de pestaña del menu "vaciaba" el feed aunque los datos seguian en la
    base de datos (se veian bien en Historial y en el Excel, pero no en el panel en vivo)."""
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        filas_alertas = conn.execute(
            "SELECT id, estacion_id, tipo, detalle, timestamp, veredicto, captura_path FROM alertas "
            "ORDER BY timestamp DESC LIMIT ?",
            (limite_por_tipo,),
        ).fetchall()
        filas_transcripciones = conn.execute(
            "SELECT estacion_id, texto, timestamp FROM transcripciones ORDER BY timestamp DESC LIMIT ?",
            (limite_por_tipo,),
        ).fetchall()
        # Nombre de empleado mas reciente por estacion: sin esto, una estacion que ya se
        # desconecto (o cuyo evento de conexion salio del panel en vivo antes de navegar a
        # otra pagina) mostraba el UUID crudo de la estacion en vez del nombre de la persona.
        filas_nombres = conn.execute(
            "SELECT estacion_id, empleado_nombre FROM eventos_conexion WHERE tipo = 'conexion' "
            "GROUP BY estacion_id HAVING MAX(timestamp)"
        ).fetchall()
        nombres_por_estacion = {fila["estacion_id"]: fila["empleado_nombre"] for fila in filas_nombres}

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


def eliminar_alertas_por_tipo(tipo: str) -> list[str]:
    """Borra todas las alertas de un `tipo` dado (usado para limpiar las de 'postura' tras
    retirar esa heuristica por falsos positivos). Devuelve las rutas de captura (relativas a
    `RUTA_CAPTURAS`) que quedaron huerfanas, para que quien llama borre tambien esos archivos
    del disco si quiere -esta funcion solo toca la base de datos-."""
    with _conexion() as conn:
        filas = conn.execute(
            "SELECT captura_path FROM alertas WHERE tipo = ? AND captura_path IS NOT NULL", (tipo,)
        ).fetchall()
        rutas = [fila[0] for fila in filas]
        conn.execute("DELETE FROM alertas WHERE tipo = ?", (tipo,))
    return rutas


def actualizar_veredicto(alerta_id: int, veredicto: str) -> bool:
    """veredicto: 'confirmada' (fue un movimiento real que valia la pena reportar) o
    'falsa_alarma' (ruido/gesto normal). Devuelve False si el id no existe."""
    with _conexion() as conn:
        cursor = conn.execute("UPDATE alertas SET veredicto = ? WHERE id = ?", (veredicto, alerta_id))
        return cursor.rowcount > 0


def registrar_transcripcion(estacion_id: str, texto: str) -> None:
    with _conexion() as conn:
        conn.execute(
            "INSERT INTO transcripciones (estacion_id, texto, timestamp) VALUES (?, ?, ?)",
            (estacion_id, texto, datetime.now(timezone.utc).isoformat()),
        )


def registrar_evento_conexion(
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
    with _conexion() as conn:
        conn.execute(
            """INSERT INTO eventos_conexion
               (estacion_id, empleado_nombre, tipo, timestamp, sede, modulo, acepto_habeas_data)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                estacion_id,
                empleado_nombre,
                tipo,
                datetime.now(timezone.utc).isoformat(),
                sede,
                modulo,
                None if acepto_habeas_data is None else int(acepto_habeas_data),
            ),
        )


def obtener_opciones() -> dict[str, list[str]]:
    """Opciones de 'sede/modalidad' y 'modulo/ventanilla' que el empleado ve en su login,
    editables por el supervisor sin tocar codigo (ver POST /api/config/opciones)."""
    with _conexion() as conn:
        filas = conn.execute("SELECT tipo, valor FROM opciones_configurables ORDER BY tipo, orden").fetchall()
    resultado: dict[str, list[str]] = {"sede": [], "modulo": []}
    for tipo, valor in filas:
        resultado.setdefault(tipo, []).append(valor)
    return resultado


def guardar_opciones(tipo: str, valores: list[str]) -> None:
    """Reemplaza por completo la lista de un tipo ('sede' o 'modulo') -asi el supervisor puede
    agregar, borrar o reordenar simplemente mandando la lista final desde el panel."""
    with _conexion() as conn:
        conn.execute("DELETE FROM opciones_configurables WHERE tipo = ?", (tipo,))
        for orden, valor in enumerate(valores):
            valor_limpio = valor.strip()
            if not valor_limpio:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO opciones_configurables (tipo, valor, orden) VALUES (?, ?, ?)",
                (tipo, valor_limpio, orden),
            )


def _calcular_sesiones(conn: sqlite3.Connection) -> list[dict]:
    """Reconstruye las 'sesiones' reales (ventanas de tiempo) de cada estacion, a partir del
    log crudo de `eventos_conexion`.

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
    filas = conn.execute(
        "SELECT estacion_id, empleado_nombre, tipo, timestamp, sede, modulo FROM eventos_conexion "
        "ORDER BY estacion_id, timestamp"
    ).fetchall()

    ahora = datetime.now(timezone.utc).isoformat()
    sesiones: list[dict] = []
    por_estacion: dict[str, list[sqlite3.Row]] = {}
    for fila in filas:
        por_estacion.setdefault(fila["estacion_id"], []).append(fila)

    for estacion_id, eventos_estacion in por_estacion.items():
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


def listar_trabajadores_para_informe() -> list[dict]:
    """Un resumen por trabajador (agrupado por nombre) para poblar la lista de 'Historial y
    Reportes': con cuantas sesiones, alertas y desde cuando tiene actividad registrada.

    Cada alerta/transcripcion se cuenta solo si cayo dentro de la ventana de tiempo de una
    sesion de ese nombre (ver `_calcular_sesiones`), no simplemente si paso alguna vez por la
    misma estacion -asi no se le suman a un trabajador alertas que en realidad son de otra
    persona que uso el mismo equipo antes o despues.
    """
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        sesiones = _calcular_sesiones(conn)
        alertas = conn.execute("SELECT estacion_id, tipo, timestamp FROM alertas").fetchall()
        transcripciones = conn.execute("SELECT estacion_id, timestamp FROM transcripciones").fetchall()

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

    # Indice de sesiones por estacion para no recorrer todas las sesiones por cada alerta.
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


def obtener_datos_reporte_trabajador(nombre: str) -> dict:
    """Todo lo necesario para armar el reporte .xlsx de un trabajador: sus sesiones (una por
    cada 'conexion' con ese nombre) y, para cada una, solo las alertas/transcripciones que
    cayeron DENTRO de esa ventana de tiempo -no toda la historia de la estacion que uso-, para
    que el reporte de una persona nunca incluya actividad de otra que compartio el mismo
    equipo en otro momento."""
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        sesiones_trabajador = [s for s in _calcular_sesiones(conn) if s["nombre"] == nombre]

        eventos: list[dict] = []
        for sesion in sesiones_trabajador:
            filas_alertas = conn.execute(
                "SELECT tipo, detalle, timestamp, veredicto, captura_path FROM alertas "
                "WHERE estacion_id = ? AND timestamp >= ? AND timestamp < ? ORDER BY timestamp",
                (sesion["estacion_id"], sesion["inicio"], sesion["fin"]),
            ).fetchall()
            for fila in filas_alertas:
                eventos.append(
                    {
                        "timestamp": fila["timestamp"],
                        "categoria": f"Alerta de {fila['tipo']}",
                        "detalle": fila["detalle"],
                        "veredicto": fila["veredicto"] or "Sin revisar",
                        "captura_path": fila["captura_path"],
                    }
                )

            filas_transcripciones = conn.execute(
                "SELECT texto, timestamp FROM transcripciones "
                "WHERE estacion_id = ? AND timestamp >= ? AND timestamp < ? ORDER BY timestamp",
                (sesion["estacion_id"], sesion["inicio"], sesion["fin"]),
            ).fetchall()
            for fila in filas_transcripciones:
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

    return {
        "nombre": nombre,
        "sesiones": sesiones_para_reporte,
        "eventos": eventos,
    }


inicializar_db()
