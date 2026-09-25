"""Hashing de contraseñas (bcrypt, irreversible) y cifrado de datos sensibles (Fernet,
reversible -numero de documento y correo, que si necesitan poder mostrarse alguna vez-).

Nunca se guarda una contraseña ni la clave de super-admin en texto plano ni cifradas de forma
reversible: siempre con bcrypt. El numero de documento y el correo si se guardan cifrados
(no hasheados) porque son datos que un administrador legitimamente podria necesitar leer, a
diferencia de una contraseña.

Como Fernet cifra distinto cada vez (usa un nonce aleatorio), no se puede usar el texto cifrado
para buscar "¿ya existe este correo?" -por eso cada campo cifrado va acompañado de un hash
determinista (SHA-256) que si sirve para eso, sin exponer el valor real en una columna de solo
lectura para busquedas.
"""
import hashlib

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def hashear_clave(clave_plana: str) -> str:
    return bcrypt.hashpw(clave_plana.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_clave(clave_plana: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(clave_plana.encode("utf-8"), hash_guardado.encode("utf-8"))
    except ValueError:
        return False  # hash_guardado corrupto/con formato invalido


def _fernet() -> Fernet:
    if not settings.fernet_key:
        raise RuntimeError(
            "Falta FERNET_KEY en backend/.env -generar una con "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`"
        )
    return Fernet(settings.fernet_key.encode("utf-8"))


def cifrar(texto_plano: str) -> str:
    return _fernet().encrypt(texto_plano.encode("utf-8")).decode("utf-8")


def descifrar(texto_cifrado: str) -> str:
    try:
        return _fernet().decrypt(texto_cifrado.encode("utf-8")).decode("utf-8")
    except InvalidToken as err:
        raise ValueError("No se pudo descifrar: dato corrupto o FERNET_KEY incorrecta") from err


def hash_busqueda(texto_plano: str) -> str:
    """Hash determinista (no reversible) para poder buscar/validar unicidad de un campo
    cifrado (correo, numero de documento) sin descifrar toda la tabla. Se normaliza a
    minusculas/sin espacios para que "Juan@Mail.com" y " juan@mail.com " cuenten como el mismo
    valor."""
    normalizado = texto_plano.strip().lower()
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()
