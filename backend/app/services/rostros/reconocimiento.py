"""Verificacion de identidad por rostro (login facial), usando DeepFace.

Distinto del pipeline de deteccion de gestos/expresion (YOLO + HSEmotion) que ya corre durante
el monitoreo: aqui no se trata de "¿hay una cara?" sino de "¿esta cara es la MISMA persona que
se registro?" -por eso hace falta un modelo de reconocimiento (que genera un vector/embedding
por rostro y compara distancias), no solo de deteccion de landmarks como el script de
referencia en `Deteccion de Rostro/face_landmarks.py` (ese solo ubica puntos faciales, no
compara identidad).

Modelo: Facenet (embedding de 128 dimensiones). Se calcula una sola vez en el registro y se
guarda en la base de datos (`usuarios.rostro_embedding`); en cada login solo se calcula el
embedding de la foto nueva y se compara contra el guardado -no hace falta releer/recalcular
la foto de registro cada vez-.
"""
import logging

import numpy as np
from deepface import DeepFace

logger = logging.getLogger(__name__)

_MODELO = "Facenet"
_DETECTOR = "retinaface"  # mas preciso que "opencv"; aqui no corre en tiempo real, solo 1 vez
# Umbral de distancia coseno para Facenet: por debajo de esto, DeepFace considera "misma
# persona" (valor estandar de la libreria para este modelo+metrica).
_UMBRAL_DISTANCIA = 0.40


def generar_embedding(imagen_bgr: np.ndarray) -> list[float] | None:
    """Devuelve el embedding facial (128 numeros) de la primera cara encontrada en la imagen,
    o None si no se pudo ubicar ninguna cara con confianza suficiente."""
    try:
        resultados = DeepFace.represent(
            img_path=imagen_bgr,
            model_name=_MODELO,
            detector_backend=_DETECTOR,
            enforce_detection=True,
        )
    except ValueError:
        # DeepFace lanza ValueError especificamente cuando no encuentra ninguna cara
        # -"Face could not be detected"-, que es un caso esperado (foto mala), no un bug.
        return None
    except Exception:
        logger.exception("Error inesperado generando embedding facial")
        return None

    if not resultados:
        return None
    return resultados[0]["embedding"]


def _distancia_coseno(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    return float(1 - np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def verificar_rostro(embedding_registrado: list[float], imagen_login_bgr: np.ndarray) -> tuple[bool, float]:
    """Compara la foto tomada en el login contra el embedding guardado en el registro.

    Devuelve `(coincide, distancia)`: `coincide=True` si la distancia esta por debajo del
    umbral (misma persona); `distancia` se devuelve siempre para poder loguear/depurar
    intentos fallidos sin exponer las imagenes."""
    embedding_login = generar_embedding(imagen_login_bgr)
    if embedding_login is None:
        return False, 1.0  # distancia maxima: no se pudo ni ubicar una cara para comparar

    distancia = _distancia_coseno(embedding_registrado, embedding_login)
    return distancia <= _UMBRAL_DISTANCIA, distancia
