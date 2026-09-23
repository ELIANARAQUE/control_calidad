"""Reconocimiento de expresion facial (FER+) sobre el recorte de cara que dan los propios
keypoints de YOLO-pose -no hace falta un detector de cara aparte, ya tenemos nariz/ojos-.

Modelo: emotion-ferplus (ONNX, ~34MB), entrenado sobre FER+ (reetiquetado del dataset FER2013
por multiples anotadores humanos, mas confiable que el FER2013 original). Corre con
onnxruntime, liviano en CPU y GPU, asi que no compite de forma significativa por VRAM con
YOLO/Whisper.
"""
import logging

import cv2
import numpy as np
import onnxruntime as ort

from app.core.config import settings
from app.services.yolo.detector import NARIZ, OJO_DER, OJO_IZQ, ancho_hombros

logger = logging.getLogger(__name__)

# Orden de salida del modelo emotion-ferplus (8 clases)
ETIQUETAS = ["neutral", "felicidad", "sorpresa", "tristeza", "enojo", "disgusto", "miedo", "desprecio"]
EMOCIONES_NEGATIVAS = {"enojo", "disgusto", "desprecio"}

_TAMANO_ENTRADA = 64  # el modelo espera imagenes en escala de grises de 64x64


def _softmax(x: np.ndarray) -> np.ndarray:
    exp = np.exp(x - np.max(x))
    return exp / exp.sum()


def recortar_cara(
    frame_bgr: np.ndarray, keypoints: np.ndarray, confianzas: np.ndarray, confianza_minima: float
) -> np.ndarray | None:
    """Estima un recuadro de cara a partir de nariz/ojos (o del ancho de hombros si los ojos
    no son fiables en este frame) y devuelve el recorte en BGR, o None si no hay suficiente
    informacion para ubicar la cara con confianza.
    """
    if len(keypoints) <= max(NARIZ, OJO_IZQ, OJO_DER) or len(confianzas) <= max(NARIZ, OJO_IZQ, OJO_DER):
        return None
    if confianzas[NARIZ] < confianza_minima:
        return None

    nariz = keypoints[NARIZ]

    if confianzas[OJO_IZQ] >= confianza_minima and confianzas[OJO_DER] >= confianza_minima:
        separacion_ojos = np.linalg.norm(keypoints[OJO_IZQ] - keypoints[OJO_DER])
        lado = separacion_ojos * 3.4  # proporcion tipica cara/separacion-de-ojos en vista frontal
    else:
        escala = ancho_hombros(keypoints, confianzas, confianza_minima)
        if escala is None:
            return None
        lado = escala * 0.65  # proporcion tipica cara/ancho-de-hombros como respaldo

    lado = max(lado, 40.0)
    alto_frame, ancho_frame = frame_bgr.shape[:2]

    x0 = int(max(0, nariz[0] - lado / 2))
    x1 = int(min(ancho_frame, nariz[0] + lado / 2))
    y0 = int(max(0, nariz[1] - lado * 0.6))  # la nariz no esta al centro vertical de la cara
    y1 = int(min(alto_frame, nariz[1] + lado * 0.4))

    if x1 - x0 < 20 or y1 - y0 < 20:
        return None
    return frame_bgr[y0:y1, x0:x1]


class DetectorEmocion:
    """Sesion de ONNX Runtime compartida (singleton) por todas las estaciones."""

    _instancia: "DetectorEmocion | None" = None

    def __new__(cls) -> "DetectorEmocion":
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self) -> None:
        if self._inicializado:
            return
        self._inicializado = True

        logger.info("Cargando modelo de expresion facial: %s", settings.emocion_modelo_path)
        # CPU alcanza de sobra para un modelo tan pequeno; se deja fuera de la GPU a
        # proposito para no competir por VRAM con YOLO/Whisper en las estaciones concurrentes.
        self.sesion = ort.InferenceSession(settings.emocion_modelo_path, providers=["CPUExecutionProvider"])
        self._nombre_entrada = self.sesion.get_inputs()[0].name

    def clasificar(self, recorte_cara_bgr: np.ndarray) -> tuple[str, float]:
        """Devuelve (etiqueta_dominante, probabilidad) para el recorte de cara dado."""
        gris = cv2.cvtColor(recorte_cara_bgr, cv2.COLOR_BGR2GRAY)
        gris = cv2.resize(gris, (_TAMANO_ENTRADA, _TAMANO_ENTRADA))
        entrada = gris.astype(np.float32).reshape(1, 1, _TAMANO_ENTRADA, _TAMANO_ENTRADA)

        salida = self.sesion.run(None, {self._nombre_entrada: entrada})[0][0]
        probabilidades = _softmax(salida)

        idx_dominante = int(np.argmax(probabilidades))
        return ETIQUETAS[idx_dominante], float(probabilidades[idx_dominante])
