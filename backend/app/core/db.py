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

        conn.execute("CREATE INDEX IF NOT EXISTS idx_alertas_estacion ON alertas(estacion_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transcripciones_estacion ON transcripciones(estacion_id)")


def registrar_alerta(estacion_id: str, detalle: str, tipo: str = "postura") -> int:
    """Guarda una alerta recien generada y devuelve su id, para que el panel de
    supervisor pueda referenciarla al confirmarla o descartarla despues.

    `tipo`: 'postura' (movimiento brusco) o 'lenguaje' (posible grosería transcrita).
    """
    with _conexion() as conn:
        cursor = conn.execute(
            "INSERT INTO alertas (estacion_id, tipo, detalle, timestamp, veredicto) VALUES (?, ?, ?, ?, NULL)",
            (estacion_id, tipo, detalle, datetime.now(timezone.utc).isoformat()),
        )
        return cursor.lastrowid


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


def registrar_evento_conexion(estacion_id: str, empleado_nombre: str | None, tipo: str) -> None:
    """tipo: 'conexion' o 'desconexion' -- log de cuando cada estacion entro/salio."""
    with _conexion() as conn:
        conn.execute(
            "INSERT INTO eventos_conexion (estacion_id, empleado_nombre, tipo, timestamp) VALUES (?, ?, ?, ?)",
            (estacion_id, empleado_nombre, tipo, datetime.now(timezone.utc).isoformat()),
        )


inicializar_db()
