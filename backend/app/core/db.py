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

    eventos = []
    for fila in filas_alertas:
        eventos.append(
            {
                "estacion_id": fila["estacion_id"],
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
                "tipo": "transcripcion",
                "timestamp": fila["timestamp"],
                "texto": fila["texto"],
            }
        )
    eventos.sort(key=lambda e: e["timestamp"])
    return eventos


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


def listar_trabajadores_para_informe() -> list[dict]:
    """Un resumen por trabajador (agrupado por nombre, que es lo que identifica a la persona
    a traves de sus distintas sesiones/estaciones) para poblar la lista de 'Historial y
    Reportes': con cuantas sesiones, alertas y desde cuando tiene actividad registrada.
    """
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        conexiones = conn.execute(
            "SELECT estacion_id, empleado_nombre, sede, modulo, timestamp FROM eventos_conexion "
            "WHERE tipo = 'conexion' ORDER BY timestamp"
        ).fetchall()
        alertas = conn.execute("SELECT estacion_id, tipo, veredicto FROM alertas").fetchall()
        transcripciones = conn.execute("SELECT estacion_id FROM transcripciones").fetchall()

    # Cada estacion queda asociada al ultimo nombre con el que se conecto (cubre el caso
    # normal de una estacion == una persona; si el mismo equipo cambio de dueño, las alertas
    # viejas se cuentan con el nombre que tenian en ese momento en su ULTIMA conexion, que es
    # la aproximacion mas simple sin guardar el nombre directamente en cada alerta).
    estacion_a_nombre: dict[str, str] = {}
    trabajadores: dict[str, dict] = {}

    for fila in conexiones:
        nombre = (fila["empleado_nombre"] or "Sin identificar").strip() or "Sin identificar"
        estacion_a_nombre[fila["estacion_id"]] = nombre
        info = trabajadores.setdefault(
            nombre,
            {
                "nombre": nombre,
                "estaciones": set(),
                "sedes": set(),
                "modulos": set(),
                "primera_conexion": fila["timestamp"],
                "ultima_conexion": fila["timestamp"],
                "sesiones": 0,
                "alertas_postura": 0,
                "alertas_lenguaje": 0,
                "alertas_expresion": 0,
                "transcripciones": 0,
            },
        )
        info["estaciones"].add(fila["estacion_id"])
        if fila["sede"]:
            info["sedes"].add(fila["sede"])
        if fila["modulo"]:
            info["modulos"].add(fila["modulo"])
        info["primera_conexion"] = min(info["primera_conexion"], fila["timestamp"])
        info["ultima_conexion"] = max(info["ultima_conexion"], fila["timestamp"])
        info["sesiones"] += 1

    for fila in alertas:
        nombre = estacion_a_nombre.get(fila["estacion_id"], "Sin identificar")
        info = trabajadores.setdefault(
            nombre,
            {
                "nombre": nombre, "estaciones": {fila["estacion_id"]}, "sedes": set(), "modulos": set(),
                "primera_conexion": None, "ultima_conexion": None, "sesiones": 0,
                "alertas_postura": 0, "alertas_lenguaje": 0, "alertas_expresion": 0, "transcripciones": 0,
            },
        )
        clave = f"alertas_{fila['tipo']}"
        if clave in info:
            info[clave] += 1

    for fila in transcripciones:
        nombre = estacion_a_nombre.get(fila["estacion_id"], "Sin identificar")
        if nombre in trabajadores:
            trabajadores[nombre]["transcripciones"] += 1

    resultado = []
    for info in trabajadores.values():
        total_alertas = info["alertas_postura"] + info["alertas_lenguaje"] + info["alertas_expresion"]
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
                "transcripciones": info["transcripciones"],
            }
        )
    resultado.sort(key=lambda t: t["ultima_conexion"] or "", reverse=True)
    return resultado


def obtener_datos_reporte_trabajador(nombre: str) -> dict:
    """Todo lo necesario para armar el reporte .xlsx de un trabajador: sus sesiones
    (conexion/desconexion), y cada alerta/transcripcion de todas las estaciones que alguna
    vez uso con ese nombre, ordenado cronologicamente."""
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        estaciones_del_trabajador = {
            fila["estacion_id"]
            for fila in conn.execute(
                "SELECT DISTINCT estacion_id FROM eventos_conexion WHERE empleado_nombre = ?", (nombre,)
            ).fetchall()
        }

        sesiones = conn.execute(
            "SELECT estacion_id, tipo, timestamp, sede, modulo, acepto_habeas_data FROM eventos_conexion "
            "WHERE empleado_nombre = ? ORDER BY timestamp",
            (nombre,),
        ).fetchall()

        eventos: list[dict] = []
        if estaciones_del_trabajador:
            marcadores = ",".join("?" * len(estaciones_del_trabajador))
            filas_alertas = conn.execute(
                f"SELECT estacion_id, tipo, detalle, timestamp, veredicto, captura_path FROM alertas "
                f"WHERE estacion_id IN ({marcadores}) ORDER BY timestamp",
                tuple(estaciones_del_trabajador),
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
                f"SELECT estacion_id, texto, timestamp FROM transcripciones "
                f"WHERE estacion_id IN ({marcadores}) ORDER BY timestamp",
                tuple(estaciones_del_trabajador),
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

    return {
        "nombre": nombre,
        "sesiones": [dict(fila) for fila in sesiones],
        "eventos": eventos,
    }


inicializar_db()
