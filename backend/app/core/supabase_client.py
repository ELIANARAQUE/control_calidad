"""Cliente compartido de Supabase (Postgres + Storage + Auth), usado por toda la capa de
persistencia (`app/core/db.py`, `app/core/cuentas.py`).

Se crea una sola vez (patron singleton perezoso) porque instanciar el cliente abre pools de
conexion HTTP internos; crear uno nuevo por cada llamada seria un desperdicio.

El cliente de supabase-py es SINCRONO (hace requests HTTP bloqueantes): las funciones que lo
usan desde codigo async (los loops de WebRTC en `tracks.py`) deben correrlo en un
ThreadPoolExecutor, igual que ya se hace con YOLO/Whisper -ver `run_in_executor` en tracks.py-.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


@lru_cache(maxsize=1)
def obtener_supabase() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "Faltan SUPABASE_URL / SUPABASE_KEY en backend/.env -el backend no puede "
            "funcionar sin la base de datos de Supabase configurada. Usa la SERVICE ROLE "
            "KEY del proyecto, no la anon key."
        )
    return create_client(settings.supabase_url, settings.supabase_key)


# Cada llamada a Supabase es un request HTTP bloqueante (supabase-py es sincrono). El resto del
# backend es asyncio (FastAPI + los loops de WebRTC en tracks.py): llamar a Supabase directo
# desde una corutina bloquearia el event loop completo durante ese round-trip de red -el mismo
# problema que ya se resolvio para la codificacion de JPEGs, ahora aplicado a cada consulta a la
# base de datos-, asi que toda llamada a Supabase se corre en este pool de hilos dedicado.
_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="supabase")


async def en_hilo(func, *args, **kwargs):
    """Corre una llamada bloqueante (tipicamente a Supabase) en el thread-pool dedicado, sin
    congelar el event loop de asyncio mientras dura el request HTTP."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))
