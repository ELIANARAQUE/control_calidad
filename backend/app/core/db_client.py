"""Cliente compartido de Postgres nativo (Railway), usado por toda la capa de
persistencia (`app/core/db.py`, `app/core/cuentas.py`).

Reemplaza a `app/core/supabase_client.py` (ya eliminado: la migracion de `db.py`/
`cuentas.py`/`estaciones.py` a este cliente esta completa).

Se usa un POOL nativo de psycopg3 (`psycopg_pool.ConnectionPool`), no una conexion por
llamada (desperdicio) ni una sola compartida entre hilos (se corrompe con consultas
simultaneas) -el mismo problema que resolvia el cliente-por-hilo de Supabase, pero aca
lo resuelve el pool directamente: cada hilo toma prestada una conexion del pool mientras
dura la consulta y la devuelve al terminar.

El driver de psycopg3 es SINCRONO (bloquea el hilo mientras dura el round-trip a la base
de datos): las funciones que lo usan desde codigo async (los loops de WebRTC en
`tracks.py`) deben correrlo en un ThreadPoolExecutor, igual que ya se hace con
YOLO/Whisper -ver `run_in_executor` en tracks.py-.
"""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg.rows import dict_row
from psycopg.types.datetime import TimestamptzBinaryLoader, TimestamptzLoader
from psycopg_pool import ConnectionPool

from app.core.config import settings

logger = logging.getLogger(__name__)


# psycopg3, por defecto, decodifica las columnas `timestamptz` como `datetime.datetime`
# nativo de Python. Supabase-py (el cliente que este modulo reemplaza) siempre devolvia
# los timestamps como strings ISO 8601 (asi via su API HTTP/JSON), y TODA la capa de
# persistencia (`app/core/db.py`) esta escrita asumiendo ese formato: compara timestamps
# con `<=`/`<` entre si y contra el string que arma `_ahora()`, los concatena en un id
# compuesto (`f"{estacion_id}|{inicio}"`), etc. Mezclar `datetime` (leido de la base) con
# `str` (generado en Python) en esas comparaciones rompe con `TypeError` -se detecto
# corriendo las pruebas de la Fase 2 contra un Postgres real, ver backend/postgres_schema.sql-.
# En vez de tocar cada comparacion de `db.py` uno por uno, se resuelve una sola vez aca: se
# registra un loader que devuelve el mismo string ISO 8601 que ya devolvia supabase-py, para
# que el resto del codigo seguido viendo el mismo tipo de dato con el que fue escrito.
class _TimestamptzComoTexto(TimestamptzLoader):
    def load(self, data: bytes) -> str:  # type: ignore[override]
        return super().load(data).isoformat()


class _TimestamptzComoTextoBinario(TimestamptzBinaryLoader):
    def load(self, data: bytes) -> str:  # type: ignore[override]
        return super().load(data).isoformat()


def _configurar_conexion(con: psycopg.Connection) -> None:
    con.adapters.register_loader("timestamptz", _TimestamptzComoTexto)
    con.adapters.register_loader("timestamptz", _TimestamptzComoTextoBinario)


# Pool nativo de conexiones a Postgres. `dict_row` hace que cada fila salga como `dict`
# (igual que hoy sale `.data` de supabase-py), para minimizar el diff cuando se migre
# `db.py` a este cliente en la proxima fase.
_pool: ConnectionPool | None = None


def _obtener_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError(
                "Falta DATABASE_URL en backend/.env -el backend no puede funcionar sin "
                "la base de datos Postgres configurada. Railway la inyecta sola al "
                "vincular el plugin de Postgres al servicio."
            )
        _pool = ConnectionPool(
            settings.database_url,
            min_size=2,
            max_size=6,
            kwargs={"row_factory": dict_row},
            configure=_configurar_conexion,
        )
    return _pool


def ejecutar(sql: str, params=None) -> list[dict]:
    """Ejecuta una consulta tomando una conexion prestada del pool y la devuelve al
    terminar. Para SELECT devuelve las filas (como dict); para INSERT/UPDATE/DELETE sin
    RETURNING devuelve lista vacia."""
    with _obtener_pool().connection() as con:
        with con.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is not None:
                return cur.fetchall()
            return []


def ejecutar_muchos(sql: str, lista_de_params) -> None:
    """Como `ejecutar`, pero corre el mismo SQL una vez por cada tupla/dict de
    `lista_de_params` (ej. el upsert del diccionario de lenguaje inapropiado, que inserta o
    actualiza muchas filas de una sola vez). Siempre parametrizado igual que `ejecutar`."""
    with _obtener_pool().connection() as con:
        with con.cursor() as cur:
            cur.executemany(sql, lista_de_params)


# Cada llamada a Postgres es una consulta bloqueante (psycopg3, en su modo sincrono, lo
# es). El resto del backend es asyncio (FastAPI + los loops de WebRTC en tracks.py):
# llamar a Postgres directo desde una corutina bloquearia el event loop completo durante
# ese round-trip -el mismo problema que ya se resolvio para la codificacion de JPEGs,
# ahora aplicado a cada consulta a la base de datos-, asi que toda llamada a Postgres se
# corre en este pool de hilos dedicado.
_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="postgres")

# Errores de conexion pasajeros: aunque psycopg_pool ya maneja bastante esto internamente
# (a diferencia del cliente HTTP de supabase-py, este es un pool real de conexiones TCP que
# se auto-repara), se reintenta igual como red de seguridad ante un corte de red momentaneo
# o un restart del servidor de base de datos.
_ERRORES_DE_CONEXION = (psycopg.OperationalError, psycopg.InterfaceError)
_REINTENTOS = 3


def _con_reintentos(func, args, kwargs):
    for intento in range(1, _REINTENTOS + 1):
        try:
            return func(*args, **kwargs)
        except _ERRORES_DE_CONEXION as err:
            if intento == _REINTENTOS:
                raise
            logger.warning("Conexion con Postgres interrumpida (%s); reintento %d de %d", type(err).__name__, intento, _REINTENTOS - 1)
            time.sleep(0.3 * intento)


async def en_hilo(func, *args, **kwargs):
    """Corre una llamada bloqueante (tipicamente a Postgres) en el thread-pool dedicado,
    sin congelar el event loop de asyncio mientras dura la consulta. Si la conexion con
    Postgres se cae a mitad de camino, reintenta con una conexion nueva del pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _con_reintentos, func, args, kwargs)
