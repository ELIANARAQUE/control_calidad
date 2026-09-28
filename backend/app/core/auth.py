"""Tokens de sesion en memoria, ahora con rol (admin/empleado) segun la cuenta real en
Supabase -antes era un usuario/clave unico y compartido; ver `app.core.cuentas` para el login
real (credenciales + verificacion facial) contra la tabla `usuarios`.

Los tokens siguen viviendo solo en memoria del proceso (no en una tabla): si el servidor se
reinicia, todos deben volver a iniciar sesion. Es una limitacion aceptada -evita depender de
una tabla de sesiones mas- pero significa que un reinicio del backend desconecta a todos.
"""
import secrets
import time

from fastapi import Header, HTTPException, Query

from app.core.config import settings

# token -> {"usuario_id": str, "nombre": str, "rol": "admin" | "empleado"}
_tokens_validos: dict[str, dict] = {}
# token -> ultimo momento (time.monotonic) en que se uso: el latido de las paginas lo renueva.
_ultimo_uso: dict[str, float] = {}

# Cookie de sesion (HttpOnly: el JavaScript de la pagina no puede leerla ni robarla). Es lo que
# el servidor revisa para dejar entrar -o no- a /empleado/ y /supervisor/: sin ella, se
# redirige a /login/ antes de servir la pagina, sin depender de ningun chequeo del navegador.
COOKIE_SESION = "qamonitor_sesion"


def crear_token(usuario_id: str, nombre: str, rol: str) -> str:
    token = secrets.token_urlsafe(32)
    _tokens_validos[token] = {"usuario_id": usuario_id, "nombre": nombre, "rol": rol}
    _ultimo_uso[token] = time.monotonic()
    return token


def cerrar_sesion(token: str) -> None:
    _tokens_validos.pop(token, None)
    _ultimo_uso.pop(token, None)


def _vigente(token: str) -> bool:
    """La sesion sigue abierta solo si alguna pagina la uso hace menos de
    `sesion_inactividad_segundos`; si no (navegador cerrado), se cierra en este momento."""
    if token not in _tokens_validos:
        return False
    if time.monotonic() - _ultimo_uso.get(token, 0) > settings.sesion_inactividad_segundos:
        cerrar_sesion(token)
        return False
    _ultimo_uso[token] = time.monotonic()
    return True


def token_valido(token: str | None) -> bool:
    """Chequeo manual (para el WebSocket del supervisor, donde una `Depends` normal de
    FastAPI no aplica igual que en una ruta HTTP)."""
    return bool(token) and _vigente(token)


def info_de_token(token: str | None) -> dict | None:
    if not token or not _vigente(token):
        return None
    return _tokens_validos.get(token)


def _token_desde_request(x_auth_token: str | None, token: str | None) -> str | None:
    return x_auth_token or token


async def requerir_sesion(
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict:
    """Dependencia de FastAPI: exige CUALQUIER sesion valida (admin o empleado). Acepta el
    token por header (llamadas fetch normales) o por query param (necesario para <img src> y
    el WebSocket, que no pueden mandar headers personalizados)."""
    token_recibido = _token_desde_request(x_auth_token, token)
    info = info_de_token(token_recibido)
    if info is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return info


async def requerir_admin(
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict:
    """Igual que `requerir_sesion`, pero ademas exige rol 'admin' -para todo lo que solo el
    supervisor puede hacer (ver estaciones, alertas, reportes, etc.)."""
    info = await requerir_sesion(x_auth_token, token)
    if info["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Esta acción requiere una cuenta de administrador")
    return info
