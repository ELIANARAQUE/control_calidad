"""Sistema de cuentas (empleados y administradores) sobre Supabase: registro con foto de
rostro, login con contraseña + verificacion facial, y el control de que solo alguien con la
clave de super-admin pueda registrarse como administrador.

Datos sensibles (numero de documento, correo) se guardan cifrados con `cryptography` (ver
`app.core.seguridad`), nunca en texto plano; la contraseña se guarda con bcrypt (irreversible).
"""
import uuid

import cv2
import numpy as np

from app.core.seguridad import cifrar, descifrar, hash_busqueda, hashear_clave, verificar_clave
from app.core.supabase_client import en_hilo, obtener_supabase
from app.services.rostros.reconocimiento import generar_embedding, verificar_rostro

NOMBRE_BUCKET_FOTOS = "fotos-empleados"


class ErrorRegistro(Exception):
    """Error de validacion al registrar una cuenta (correo/documento duplicado, foto sin
    rostro detectable, clave de super-admin incorrecta, etc.) -se traduce a un 400 en la API."""


def _decodificar_imagen(foto_bytes: bytes) -> np.ndarray:
    arreglo = np.frombuffer(foto_bytes, dtype=np.uint8)
    imagen = cv2.imdecode(arreglo, cv2.IMREAD_COLOR)
    if imagen is None:
        raise ErrorRegistro("No se pudo leer la imagen enviada (formato no soportado o archivo corrupto)")
    return imagen


# ============================================================================
# Tipos de documento (catalogo editable desde la base de datos)
# ============================================================================

def _obtener_tipos_documento_sync() -> list[dict]:
    filas = obtener_supabase().table("tipos_documento").select("id, nombre").order("nombre").execute()
    return filas.data


async def obtener_tipos_documento() -> list[dict]:
    return await en_hilo(_obtener_tipos_documento_sync)


# ============================================================================
# Super-admin (clave requerida para poder registrar una cuenta con rol admin)
# ============================================================================

def _verificar_clave_super_admin_sync(clave: str) -> bool:
    fila = obtener_supabase().table("super_admin").select("clave_hash").eq("id", 1).limit(1).execute()
    if not fila.data:
        return False
    return verificar_clave(clave, fila.data[0]["clave_hash"])


async def verificar_clave_super_admin(clave: str) -> bool:
    return await en_hilo(_verificar_clave_super_admin_sync, clave)


# ============================================================================
# Registro
# ============================================================================

def _crear_usuario_sync(
    nombre: str,
    tipo_documento_id: int,
    numero_documento: str,
    correo: str,
    clave: str,
    rol: str,
    foto_bytes: bytes,
) -> dict:
    supabase = obtener_supabase()

    hash_documento = hash_busqueda(numero_documento)
    hash_correo = hash_busqueda(correo)

    ya_existe_documento = (
        supabase.table("usuarios").select("id").eq("numero_documento_hash", hash_documento).limit(1).execute()
    )
    if ya_existe_documento.data:
        raise ErrorRegistro("Ya existe una cuenta registrada con ese número de documento")

    ya_existe_correo = supabase.table("usuarios").select("id").eq("correo_hash", hash_correo).limit(1).execute()
    if ya_existe_correo.data:
        raise ErrorRegistro("Ya existe una cuenta registrada con ese correo electrónico")

    imagen = _decodificar_imagen(foto_bytes)
    embedding = generar_embedding(imagen)
    if embedding is None:
        raise ErrorRegistro(
            "No se detectó ningún rostro en la foto. Asegúrate de estar en un sitio bien "
            "iluminado, de frente a la cámara, e intenta de nuevo."
        )

    usuario_id = str(uuid.uuid4())
    ok_jpeg, buffer_jpeg = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok_jpeg:
        raise ErrorRegistro("No se pudo procesar la foto enviada")

    ruta_storage = f"{usuario_id}/rostro.jpg"
    supabase.storage.from_(NOMBRE_BUCKET_FOTOS).upload(
        ruta_storage, buffer_jpeg.tobytes(), {"content-type": "image/jpeg", "upsert": "true"}
    )

    fila = {
        "id": usuario_id,
        "nombre": nombre,
        "tipo_documento_id": tipo_documento_id,
        "numero_documento_cifrado": cifrar(numero_documento),
        "numero_documento_hash": hash_documento,
        "correo_cifrado": cifrar(correo),
        "correo_hash": hash_correo,
        "clave_hash": hashear_clave(clave),
        "rol": rol,
        "foto_url": ruta_storage,
        "rostro_embedding": embedding,
    }
    respuesta = supabase.table("usuarios").insert(fila).execute()
    return respuesta.data[0]


async def crear_usuario(
    nombre: str,
    tipo_documento_id: int,
    numero_documento: str,
    correo: str,
    clave: str,
    rol: str,
    foto_bytes: bytes,
) -> dict:
    """Crea la cuenta (empleado o admin -la clave de super-admin ya se debe haber validado
    ANTES de llamar a esto si rol == 'admin', ver el endpoint de registro). Lanza
    `ErrorRegistro` si el correo/documento ya existen o si la foto no tiene un rostro
    detectable."""
    return await en_hilo(
        _crear_usuario_sync, nombre, tipo_documento_id, numero_documento, correo, clave, rol, foto_bytes
    )


# ============================================================================
# Login: paso 1 (credenciales) y paso 2 (verificacion facial)
# ============================================================================

def _validar_credenciales_sync(correo: str, clave: str) -> dict | None:
    fila = (
        obtener_supabase()
        .table("usuarios")
        .select("id, nombre, clave_hash, rol")
        .eq("correo_hash", hash_busqueda(correo))
        .limit(1)
        .execute()
    )
    if not fila.data:
        return None
    usuario = fila.data[0]
    if not verificar_clave(clave, usuario["clave_hash"]):
        return None
    return {"id": usuario["id"], "nombre": usuario["nombre"], "rol": usuario["rol"]}


async def validar_credenciales(correo: str, clave: str) -> dict | None:
    """Primer paso del login: solo usuario/clave. Si son correctas, devuelve
    `{id, nombre, rol}` -el login todavia no queda completo, falta la verificacion facial-."""
    return await en_hilo(_validar_credenciales_sync, correo, clave)


def _verificar_rostro_login_sync(usuario_id: str, foto_bytes: bytes) -> tuple[bool, float]:
    fila = (
        obtener_supabase().table("usuarios").select("rostro_embedding").eq("id", usuario_id).limit(1).execute()
    )
    if not fila.data or not fila.data[0]["rostro_embedding"]:
        return False, 1.0
    imagen = _decodificar_imagen(foto_bytes)
    return verificar_rostro(fila.data[0]["rostro_embedding"], imagen)


async def verificar_rostro_login(usuario_id: str, foto_bytes: bytes) -> tuple[bool, float]:
    """Segundo paso del login: compara la foto tomada en el momento contra el rostro guardado
    en el registro de esa cuenta. Devuelve `(coincide, distancia)`."""
    return await en_hilo(_verificar_rostro_login_sync, usuario_id, foto_bytes)


def _obtener_correo_descifrado_sync(usuario_id: str) -> str | None:
    fila = obtener_supabase().table("usuarios").select("correo_cifrado").eq("id", usuario_id).limit(1).execute()
    if not fila.data:
        return None
    return descifrar(fila.data[0]["correo_cifrado"])


async def obtener_correo_descifrado(usuario_id: str) -> str | None:
    """Uso administrativo puntual (ej. mostrarle a un admin el correo de un usuario); el
    correo nunca se expone al frontend salvo que explicitamente se pida esto."""
    return await en_hilo(_obtener_correo_descifrado_sync, usuario_id)
