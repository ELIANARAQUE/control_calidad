"""Cuentas: catalogo de tipos de documento, registro (empleado/admin, con foto de rostro), y
login en dos pasos -credenciales primero, verificacion facial despues- contra la tabla
`usuarios` de Supabase. Reemplaza el login unico admin/admin123 de antes.
"""
import re

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.auth import COOKIE_SESION, cerrar_sesion, crear_token
from app.core.cuentas import (
    ErrorRegistro,
    crear_usuario,
    obtener_tipos_documento,
    validar_credenciales,
    verificar_clave_super_admin,
    verificar_rostro_login,
)

router = APIRouter()

_REGEX_NOMBRE = re.compile(r"^[A-Za-zÀ-ÿ\s]{1,32}$")  # letras y espacios, sin numeros/simbolos
_REGEX_DOCUMENTO = re.compile(r"^[0-9]{1,15}$")  # solo digitos: sin letras, espacios ni simbolos
_REGEX_CORREO = re.compile(r"^[^\s@]+@[^\s@]+\.com$")  # exige "@" y ".com", sin espacios


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
    if not _REGEX_CORREO.match(correo):
        raise HTTPException(status_code=400, detail="El correo debe contener \"@\" y terminar en \".com\", sin espacios")
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
