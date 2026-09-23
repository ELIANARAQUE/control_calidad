"""Persistencia minima en SQLite para las alertas de postura.

Objetivo: que el supervisor pueda marcar cada alerta como "confirmada" o "falsa alarma"
desde el panel, y que esas etiquetas queden guardadas. Con unas semanas de uso real esto
se convierte en el dataset etiquetado necesario para entrenar un modelo temporal (fase 2),
sin tener que grabar y anotar video manualmente desde cero.

SQLite (no Postgres) porque el volumen -pocas alertas por estacion al dia, 12-15
estaciones- no justifica un motor de base de datos aparte.
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
                detalle TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                veredicto TEXT
            )
            """
        )


def registrar_alerta(estacion_id: str, detalle: str) -> int:
    """Guarda una alerta recien generada y devuelve su id, para que el panel de
    supervisor pueda referenciarla al confirmarla o descartarla despues."""
    with _conexion() as conn:
        cursor = conn.execute(
            "INSERT INTO alertas (estacion_id, detalle, timestamp, veredicto) VALUES (?, ?, ?, NULL)",
            (estacion_id, detalle, datetime.now(timezone.utc).isoformat()),
        )
        return cursor.lastrowid


def actualizar_veredicto(alerta_id: int, veredicto: str) -> bool:
    """veredicto: 'confirmada' (fue un movimiento real que valia la pena reportar) o
    'falsa_alarma' (ruido/gesto normal). Devuelve False si el id no existe."""
    with _conexion() as conn:
        cursor = conn.execute("UPDATE alertas SET veredicto = ? WHERE id = ?", (veredicto, alerta_id))
        return cursor.rowcount > 0


inicializar_db()
