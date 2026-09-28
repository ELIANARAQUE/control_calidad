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


def desvio_horizontal_nariz(imagen_bgr: np.ndarray) -> float | None:
    """Que tan girada esta la cabeza: desplazamiento horizontal de la nariz respecto al punto
    medio entre los ojos, medido en "distancias entre ojos". ~0 = de frente; cerca de +-0.3 o
    mas = perfil. Devuelve None si no se pudo ubicar la cara o sus puntos."""
    try:
        caras = DeepFace.extract_faces(img_path=imagen_bgr, detector_backend=_DETECTOR, enforce_detection=True)
    except ValueError:
        return None
    if not caras:
        return None
    area = caras[0].get("facial_area", {})
    ojo_a, ojo_b, nariz = area.get("left_eye"), area.get("right_eye"), area.get("nose")
    if not (ojo_a and ojo_b and nariz):
        return None
    distancia_ojos = abs(ojo_a[0] - ojo_b[0])
    if distancia_ojos < 1:
        # Perfil muy marcado: los dos ojos quedan casi en el mismo punto horizontal.
        return 1.0
    medio = (ojo_a[0] + ojo_b[0]) / 2
    return (nariz[0] - medio) / distancia_ojos


def _distancia_coseno(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    return float(1 - np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def embeddings_de(rostro_guardado) -> list[list[float]]:
    """Normaliza lo guardado en `usuarios.rostro_embedding`: registros nuevos guardan
    `{"frontal": [...], "izquierda": [...], "derecha": [...]}`; los viejos, un solo vector."""
    if not rostro_guardado:
        return []
    if isinstance(rostro_guardado, dict):
        return [v for v in rostro_guardado.values() if v]
    return [rostro_guardado]


def distancia_minima(embedding: list[float], rostro_guardado) -> float:
    candidatos = embeddings_de(rostro_guardado)
    if not candidatos:
        return 1.0
    return min(_distancia_coseno(embedding, c) for c in candidatos)


def es_misma_persona(distancia: float) -> bool:
    return distancia <= _UMBRAL_DISTANCIA


def verificar_rostro(rostro_guardado, imagen_login_bgr: np.ndarray) -> tuple[bool, float]:
    """Compara la foto del login contra los rostros del registro (frontal y laterales) y se
    queda con la distancia mas corta. Devuelve `(coincide, distancia)`."""
    embedding_login = generar_embedding(imagen_login_bgr)
    if embedding_login is None:
        return False, 1.0  # no se pudo ni ubicar una cara para comparar

    distancia = distancia_minima(embedding_login, rostro_guardado)
    return es_misma_persona(distancia), distancia
