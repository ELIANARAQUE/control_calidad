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


def listar_alertas_para_informe() -> list[dict]:
    """Todas las alertas (con su veredicto, si ya se reviso) para el informe descargable
    del supervisor, mas reciente primero."""
    with _conexion() as conn:
        conn.row_factory = sqlite3.Row
        filas = conn.execute(
            "SELECT id, estacion_id, tipo, detalle, timestamp, veredicto FROM alertas ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(fila) for fila in filas]


inicializar_db()
