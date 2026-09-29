"""Sistema de cuentas (empleados y administradores) sobre Supabase: registro con foto de
rostro, login con contraseña + verificacion facial, y el control de que solo alguien con la
clave de super-admin pueda registrarse como administrador.

Datos sensibles (numero de documento, correo) se guardan cifrados con `cryptography` (ver
`app.core.seguridad`), nunca en texto plano; la contraseña se guarda con bcrypt (irreversible).
"""
import uuid

import cv2
import numpy as np

from app.core.seguridad import cifrar, cifrar_bytes, descifrar, hash_busqueda, hashear_clave, verificar_clave
from app.core.supabase_client import en_hilo, obtener_supabase
from app.services.rostros.reconocimiento import (
    desvio_horizontal_nariz,
    distancia_minima,
    es_misma_persona,
    generar_embedding,
    verificar_rostro,
)

NOMBRE_BUCKET_FOTOS = "fotos-empleados"
ANGULOS_FOTO = ("frontal", "izquierda", "derecha")
_NOMBRE_ANGULO = {"frontal": "frontal", "izquierda": "lateral izquierda", "derecha": "lateral derecha"}
# Desvio de la nariz respecto al centro de los ojos, en "distancias entre ojos" (ver
# `desvio_horizontal_nariz`): de frente ~0; perfil tipico por encima de 0.3.
_MAX_DESVIO_FRONTAL = 0.22
_MIN_DESVIO_LATERAL = 0.28


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

def _rostro_ya_registrado(supabase, embedding_frontal: list[float]) -> bool:
    """Un mismo rostro no puede tener dos cuentas: se compara contra todos los rostros ya
    registrados (con la misma regla de distancia que usa el login)."""
    filas = supabase.table("usuarios").select("rostro_embedding").execute().data
    return any(es_misma_persona(distancia_minima(embedding_frontal, f["rostro_embedding"])) for f in filas)


def _crear_usuario_sync(
    nombre: str,
    tipo_documento_id: int,
    numero_documento: str,
    correo: str,
    clave: str,
    rol: str,
    fotos_bytes: dict[str, bytes],
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

    imagenes: dict[str, np.ndarray] = {}
    embeddings: dict[str, list[float]] = {}
    for angulo in ANGULOS_FOTO:
        if not fotos_bytes.get(angulo):
            raise ErrorRegistro(f"Falta la foto {_NOMBRE_ANGULO[angulo]}")
        imagenes[angulo] = _decodificar_imagen(fotos_bytes[angulo])
        embedding = generar_embedding(imagenes[angulo])
        if embedding is None:
            raise ErrorRegistro(
                f"No se detectó un rostro en la foto {_NOMBRE_ANGULO[angulo]}. Asegúrate de estar "
                "en un sitio iluminado, con fondo blanco si es posible, y de que se vea tu cara completa."
            )
        # Segunda barrera (la primera es la guia de camara del navegador): la foto frontal debe
        # estar de frente y las laterales, de perfil -si alguien sube una foto que no
        # corresponde, se rechaza aqui aunque se haya saltado la validacion del navegador-.
        desvio = desvio_horizontal_nariz(imagenes[angulo])
        if desvio is not None:
            if angulo == "frontal" and abs(desvio) > _MAX_DESVIO_FRONTAL:
                raise ErrorRegistro("La foto frontal no está de frente: mira directo a la cámara y tómala de nuevo")
            if angulo != "frontal" and abs(desvio) < _MIN_DESVIO_LATERAL:
                raise ErrorRegistro(
                    f"La foto {_NOMBRE_ANGULO[angulo]} parece de frente: gira más la cabeza y tómala de nuevo"
                )
        embeddings[angulo] = embedding

    if _rostro_ya_registrado(supabase, embeddings["frontal"]):
        raise ErrorRegistro("Usuario ya está registrado: este rostro ya tiene una cuenta")

    usuario_id = str(uuid.uuid4())
    rutas_fotos: dict[str, str] = {}
    for angulo, imagen in imagenes.items():
        ok_jpeg, buffer_jpeg = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok_jpeg:
            raise ErrorRegistro(f"No se pudo procesar la foto {_NOMBRE_ANGULO[angulo]}")
        # La foto del rostro es un dato biometrico sensible: se sube CIFRADA (Fernet), asi que
        # quien tenga acceso al bucket de Storage solo ve bytes ilegibles, no la cara.
        ruta = f"{usuario_id}/{angulo}.jpg.enc"
        supabase.storage.from_(NOMBRE_BUCKET_FOTOS).upload(
            ruta, cifrar_bytes(buffer_jpeg.tobytes()), {"content-type": "application/octet-stream", "upsert": "true"}
        )
        rutas_fotos[angulo] = ruta

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
        "foto_url": rutas_fotos["frontal"],
        "fotos": rutas_fotos,
        "rostro_embedding": embeddings,
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
    fotos_bytes: dict[str, bytes],
) -> dict:
    """Crea la cuenta (empleado o admin -la clave de super-admin ya se debe haber validado
    ANTES de llamar a esto si rol == 'admin'). `fotos_bytes` trae las tres fotos del registro
    ('frontal', 'izquierda', 'derecha'). Lanza `ErrorRegistro` si el correo/documento ya
    existen, si alguna foto no tiene un rostro detectable, o si ese rostro ya esta registrado."""
    return await en_hilo(
        _crear_usuario_sync, nombre, tipo_documento_id, numero_documento, correo, clave, rol, fotos_bytes
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


# ============================================================================
# Recuperacion de contraseña (la hace un administrador desde su panel)
# ============================================================================

def _buscar_usuario_por_correo_sync(correo: str) -> dict | None:
    fila = (
        obtener_supabase()
        .table("usuarios")
        .select("id, nombre, rol")
        .eq("correo_hash", hash_busqueda(correo))
        .limit(1)
        .execute()
    )
    return fila.data[0] if fila.data else None


async def buscar_usuario_por_correo(correo: str) -> dict | None:
    """`{id, nombre, rol}` de la cuenta con ese correo, o None si no existe."""
    return await en_hilo(_buscar_usuario_por_correo_sync, correo)


def _obtener_usuario_por_id_sync(usuario_id: str) -> dict | None:
    fila = obtener_supabase().table("usuarios").select("id, nombre, rol").eq("id", usuario_id).limit(1).execute()
    return fila.data[0] if fila.data else None


async def obtener_usuario_por_id(usuario_id: str) -> dict | None:
    """`{id, nombre, rol}` de la cuenta por su id, o None si no existe. Se usa para resolver el
    nombre/rol REALES al emitir el token de sesion en el paso 2 del login -nunca se confia en lo
    que mande el formulario del cliente, porque un empleado podria mandar rol='admin' y escalar
    privilegios aunque su propia verificacion facial sea legitima."""
    return await en_hilo(_obtener_usuario_por_id_sync, usuario_id)


def _cambiar_clave_sync(usuario_id: str, clave_nueva: str) -> None:
    obtener_supabase().table("usuarios").update({"clave_hash": hashear_clave(clave_nueva)}).eq("id", usuario_id).execute()


async def cambiar_clave(usuario_id: str, clave_nueva: str) -> None:
    """Reemplaza la contraseña de la cuenta (se guarda con bcrypt, como en el registro)."""
    await en_hilo(_cambiar_clave_sync, usuario_id, clave_nueva)
