"""Cuentas: catalogo de tipos de documento, registro (empleado/admin, con foto de rostro), y
login en dos pasos -credenciales primero, verificacion facial despues- contra la tabla
`usuarios` de Supabase. Reemplaza el login unico admin/admin123 de antes.
"""
import re

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.auth import COOKIE_SESION, cerrar_sesion, crear_token, info_de_token, requerir_admin, requerir_sesion
from app.core.cuentas import (
    ErrorRegistro,
    buscar_usuario_por_correo,
    cambiar_clave,
    crear_usuario,
    obtener_tipos_documento,
    validar_credenciales,
    verificar_clave_super_admin,
    verificar_rostro_login,
)

router = APIRouter()

_REGEX_NOMBRE = re.compile(r"^[A-Za-zÀ-ÿ\s]{1,32}$")  # letras y espacios, sin numeros/simbolos
_REGEX_DOCUMENTO = re.compile(r"^[0-9]{1,15}$")  # solo digitos: sin letras, espacios ni simbolos
DOMINIO_CORREO = "@universitariadecolombia.edu.co"
_MENSAJE_CORREO = f"El correo no puede tener espacios y debe terminar en {DOMINIO_CORREO}"


def correo_valido(correo: str) -> bool:
    """Las dos unicas reglas del correo: sin espacios y terminado en el dominio institucional."""
    return (
        not any(c.isspace() for c in correo)
        and correo.lower().endswith(DOMINIO_CORREO)
        and len(correo) > len(DOMINIO_CORREO)
    )


@router.get("/auth/tipos-documento")
async def tipos_documento() -> list[dict]:
    """Publico: el formulario de registro necesita esto para llenar el select, antes de que
    exista ninguna sesion."""
    return await obtener_tipos_documento()


@router.post("/auth/registro")
async def registro(
    nombre: str = Form(...),
    tipo_documento_id: int = Form(...),
    numero_documento: str = Form(...),
    correo: str = Form(...),
    clave: str = Form(...),
    confirmar_clave: str = Form(...),
    rol: str = Form(...),
    clave_super_admin: str | None = Form(default=None),
    foto_frontal: UploadFile = File(...),
    foto_izquierda: UploadFile = File(...),
    foto_derecha: UploadFile = File(...),
) -> dict:
    nombre = nombre.strip()
    numero_documento = numero_documento.strip()
    correo = correo.strip()

    if not _REGEX_NOMBRE.match(nombre):
        raise HTTPException(status_code=400, detail="El nombre debe tener máximo 32 letras, sin números ni símbolos")
    if not _REGEX_DOCUMENTO.match(numero_documento):
        raise HTTPException(
            status_code=400, detail="El número de documento debe tener máximo 15 dígitos, solo números"
        )
    if not correo_valido(correo):
        raise HTTPException(status_code=400, detail=_MENSAJE_CORREO)
    if " " in clave or " " in confirmar_clave:
        raise HTTPException(status_code=400, detail="La contraseña no puede contener espacios")
    if not (1 <= len(clave) <= 16):
        raise HTTPException(status_code=400, detail="La contraseña debe tener máximo 16 caracteres")
    if clave != confirmar_clave:
        raise HTTPException(status_code=400, detail="Las contraseñas no coinciden")
    if rol not in ("empleado", "admin"):
        raise HTTPException(status_code=400, detail="rol debe ser 'empleado' o 'admin'")

    if rol == "admin":
        if not clave_super_admin or not await verificar_clave_super_admin(clave_super_admin):
            raise HTTPException(status_code=403, detail="Clave de super-admin incorrecta")

    fotos_bytes = {
        "frontal": await foto_frontal.read(),
        "izquierda": await foto_izquierda.read(),
        "derecha": await foto_derecha.read(),
    }
    if not all(fotos_bytes.values()):
        raise HTTPException(status_code=400, detail="Debes tomar las tres fotos: frontal, lateral izquierda y lateral derecha")

    try:
        usuario = await crear_usuario(
            nombre=nombre,
            tipo_documento_id=tipo_documento_id,
            numero_documento=numero_documento,
            correo=correo,
            clave=clave,
            rol=rol,
            fotos_bytes=fotos_bytes,
        )
    except ErrorRegistro as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    destino = "/empleado/" if rol == "empleado" else "/supervisor/"
    return {"ok": True, "usuario_id": usuario["id"], "rol": rol, "destino": destino}


class Credenciales(BaseModel):
    correo: str
    clave: str


@router.post("/auth/login")
async def login(cuerpo: Credenciales) -> dict:
    """Paso 1 del login: solo credenciales. Si son correctas, el frontend debe abrir la
    verificacion facial (paso 2, `/auth/verificar-rostro`) antes de recibir un token real."""
    usuario = await validar_credenciales(cuerpo.correo.strip(), cuerpo.clave)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    return {"requiere_rostro": True, "usuario_id": usuario["id"], "nombre": usuario["nombre"], "rol": usuario["rol"]}


@router.post("/auth/verificar-rostro")
async def verificar_rostro(usuario_id: str = Form(...), nombre: str = Form(...), rol: str = Form(...), foto: UploadFile = File(...)) -> dict:
    """Paso 2 del login: la foto tomada en vivo debe coincidir con el rostro guardado en el
    registro de esa cuenta. Solo aqui se emite el token de sesion real."""
    foto_bytes = await foto.read()
    if not foto_bytes:
        raise HTTPException(status_code=400, detail="No se recibió ninguna foto para verificar")

    coincide, distancia = await verificar_rostro_login(usuario_id, foto_bytes)
    if not coincide:
        raise HTTPException(status_code=401, detail="El rostro no coincide con el de la cuenta registrada")

    token = crear_token(usuario_id, nombre, rol)
    destino = "/empleado/" if rol == "empleado" else "/supervisor/"
    respuesta = JSONResponse({"token": token, "rol": rol, "nombre": nombre, "destino": destino})
    respuesta.set_cookie(COOKIE_SESION, token, httponly=True, samesite="lax", path="/")
    return respuesta


@router.get("/auth/sesion")
async def sesion_actual(request: Request) -> dict:
    """Datos de la sesion abierta en ESTE navegador (por la cookie). Lo usa una pestaña nueva:
    su sessionStorage empieza vacio, pero la cookie de sesion se comparte entre pestañas."""
    token = request.cookies.get(COOKIE_SESION)
    sesion = info_de_token(token)
    if sesion is None:
        raise HTTPException(status_code=401, detail="No hay una sesión abierta")
    destino = "/empleado/" if sesion["rol"] == "empleado" else "/supervisor/"
    return {"token": token, "nombre": sesion["nombre"], "rol": sesion["rol"], "destino": destino}


@router.post("/auth/latido")
async def latido(_sesion: dict = Depends(requerir_sesion)) -> dict:
    """Cada pagina abierta llama aqui cada 25 s para mantener viva su sesion. Si deja de llegar
    (se cerro el navegador), la sesion se cierra sola (ver `sesion_inactividad_segundos`)."""
    return {"ok": True}


@router.post("/auth/logout")
async def logout(
    request: Request,
    x_auth_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> JSONResponse:
    """Cierra la sesion (invalida el token en el servidor y borra la cookie). No exige una
    sesion valida: si ya expiro, igual se limpia la cookie sin dar error."""
    cerrar_sesion(x_auth_token or token or request.cookies.get(COOKIE_SESION) or "")
    respuesta = JSONResponse({"ok": True})
    respuesta.delete_cookie(COOKIE_SESION, path="/")
    return respuesta


# --- Recuperacion de contraseña: un administrador se la cambia a un empleado que la olvido ---

class CorreoRecuperacion(BaseModel):
    correo: str


class ClaveNueva(BaseModel):
    correo: str
    clave: str
    confirmar_clave: str


async def _empleado_por_correo(correo: str) -> dict:
    usuario = await buscar_usuario_por_correo(correo.strip())
    if usuario is None:
        raise HTTPException(status_code=404, detail="No existe ninguna cuenta registrada con ese correo")
    if usuario["rol"] != "empleado":
        raise HTTPException(
            status_code=403, detail="Ese correo es de una cuenta de administrador: desde aquí solo se recuperan cuentas de empleado"
        )
    return usuario


@router.post("/auth/recuperacion/verificar")
async def verificar_correo_recuperacion(cuerpo: CorreoRecuperacion, _admin: dict = Depends(requerir_admin)) -> dict:
    usuario = await _empleado_por_correo(cuerpo.correo)
    return {"existe": True, "nombre": usuario["nombre"]}


@router.post("/auth/recuperacion/cambiar")
async def cambiar_clave_recuperacion(cuerpo: ClaveNueva, _admin: dict = Depends(requerir_admin)) -> dict:
    if " " in cuerpo.clave or " " in cuerpo.confirmar_clave:
        raise HTTPException(status_code=400, detail="La contraseña no puede contener espacios")
    if not (1 <= len(cuerpo.clave) <= 16):
        raise HTTPException(status_code=400, detail="La contraseña debe tener entre 1 y 16 caracteres")
    if cuerpo.clave != cuerpo.confirmar_clave:
        raise HTTPException(status_code=400, detail="Las contraseñas no coinciden")
    usuario = await _empleado_por_correo(cuerpo.correo)
    await cambiar_clave(usuario["id"], cuerpo.clave)
    return {"ok": True, "nombre": usuario["nombre"]}
