"""Autenticacion simple del panel de supervisor: un usuario/clave compartido (configurable
por .env) que genera un token opaco guardado en memoria. No es un sistema de cuentas por
persona -no hace falta en una red local cerrada con un solo rol de supervisor-, pero evita
que cualquiera en la red vea las camaras y transcripciones con solo conocer la URL.
"""
import secrets

from fastapi import Header, HTTPException, Query

from app.core.config import settings

# Tokens de sesion vigentes. En memoria: si el servidor se reinicia, todos los supervisores
# deben volver a iniciar sesion (aceptable para este alcance, evita depender de una tabla mas).
_tokens_validos: set[str] = set()


def iniciar_sesion(usuario: str, clave: str) -> str:
    if not secrets.compare_digest(usuario, settings.admin_usuario) or not secrets.compare_digest(
        clave, settings.admin_clave
    ):
        raise HTTPException(status_code=401, detail="Usuario o clave incorrectos")
    token = secrets.token_urlsafe(32)
    _tokens_validos.add(token)
    return token


def cerrar_sesion(token: str) -> None:
    _tokens_validos.discard(token)


def token_valido(token: str | None) -> bool:
    """Chequeo manual (para el WebSocket del supervisor, donde una `Depends` normal de
    FastAPI no aplica igual que en una ruta HTTP)."""
    return bool(token) and token in _tokens_validos


async def requerir_admin(
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> str:
    """Dependencia de FastAPI: acepta el token por header (llamadas fetch normales) o por
    query param (necesario para <img src> y el WebSocket, que no pueden mandar headers
    personalizados)."""
    token_recibido = x_auth_token or token
    if not token_recibido or token_recibido not in _tokens_validos:
        raise HTTPException(status_code=401, detail="Sesión de supervisor inválida o expirada")
    return token_recibido
