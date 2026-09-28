"""Cliente compartido de Supabase (Postgres + Storage + Auth), usado por toda la capa de
persistencia (`app/core/db.py`, `app/core/cuentas.py`).

Se crea un cliente por cada hilo del pool (no uno por llamada, que seria un desperdicio de
conexiones; ni uno solo compartido, que se corrompe con consultas simultaneas).

El cliente de supabase-py es SINCRONO (hace requests HTTP bloqueantes): las funciones que lo
usan desde codigo async (los loops de WebRTC en `tracks.py`) deben correrlo en un
ThreadPoolExecutor, igual que ya se hace con YOLO/Whisper -ver `run_in_executor` en tracks.py-.
"""
import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from supabase import Client, create_client

from app.core.config import settings

logger = logging.getLogger(__name__)

# Un cliente POR HILO: el cliente de supabase-py usa una conexion HTTP/2 y compartirla entre
# los 6 hilos del pool a la vez provocaba "httpx.RemoteProtocolError: Server disconnected"
# (sobre todo cuando una pagina hace varias consultas en paralelo, como Historial y Reportes).
_local = threading.local()


def obtener_supabase() -> Client:
    cliente = getattr(_local, "cliente", None)
    if cliente is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "Faltan SUPABASE_URL / SUPABASE_KEY en backend/.env -el backend no puede "
                "funcionar sin la base de datos de Supabase configurada. Usa la SERVICE ROLE "
                "KEY del proyecto, no la anon key."
            )
        cliente = create_client(settings.supabase_url, settings.supabase_key)
        _local.cliente = cliente
    return cliente


def _descartar_cliente_del_hilo() -> None:
    _local.cliente = None


# Cada llamada a Supabase es un request HTTP bloqueante (supabase-py es sincrono). El resto del
# backend es asyncio (FastAPI + los loops de WebRTC en tracks.py): llamar a Supabase directo
# desde una corutina bloquearia el event loop completo durante ese round-trip de red -el mismo
# problema que ya se resolvio para la codificacion de JPEGs, ahora aplicado a cada consulta a la
# base de datos-, asi que toda llamada a Supabase se corre en este pool de hilos dedicado.
_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="supabase")

# Errores de red pasajeros: Supabase cierra conexiones inactivas, y la siguiente consulta que
# intenta usarla falla aunque el servidor este bien. Se reintenta con una conexion nueva.
_ERRORES_DE_CONEXION = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.TimeoutException)
_REINTENTOS = 3


def _con_reintentos(func, args, kwargs):
    for intento in range(1, _REINTENTOS + 1):
        try:
            return func(*args, **kwargs)
        except _ERRORES_DE_CONEXION as err:
            _descartar_cliente_del_hilo()
            if intento == _REINTENTOS:
                raise
            logger.warning("Conexion con Supabase interrumpida (%s); reintento %d de %d", type(err).__name__, intento, _REINTENTOS - 1)
            time.sleep(0.3 * intento)


async def en_hilo(func, *args, **kwargs):
    """Corre una llamada bloqueante (tipicamente a Supabase) en el thread-pool dedicado, sin
    congelar el event loop de asyncio mientras dura el request HTTP. Si la conexion con
    Supabase se cae a mitad de camino, reintenta con una conexion nueva."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _con_reintentos, func, args, kwargs)
