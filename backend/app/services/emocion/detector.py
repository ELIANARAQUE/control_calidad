"""Reconocimiento de expresion facial sobre el recorte de cara que dan los propios
keypoints de YOLO-pose -no hace falta un detector de cara aparte, ya tenemos nariz/ojos-.

Modelo: HSEmotion `enet_b2_8` (EfficientNet-B2, ONNX), entrenado sobre AffectNet -caras
reales "en la calle", con expresiones naturales y sutiles-. El modelo que se usaba antes
(`enet_b0_8_best_afew`) estaba ajustado a AFEW, un dataset de escenas de PELICULAS con
expresiones actuadas/exageradas: por eso habia que sobreactuar el gesto para que lo captara.
Corre en ~20 ms por cara en CPU, sin competir por VRAM con YOLO/Whisper.

Nota: `hsemotion_onnx` descarga el .onnx la primera vez a `~/.hsemotion/` (no viene
empaquetado). El import de `urllib.request` de abajo es un workaround a un bug real de esa
libreria: su modulo usa `urllib.request.urlretrieve` sin importar el submodulo `request`,
lo que revienta con `AttributeError` si nadie mas lo importo antes en el proceso.
"""
import logging
import urllib.request  # noqa: F401  (workaround: ver docstring del modulo)

import numpy as np
from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

from app.core.config import settings
from app.services.yolo.detector import NARIZ, OJO_DER, OJO_IZQ, ancho_hombros

logger = logging.getLogger(__name__)

# HSEmotion devuelve las etiquetas en ingles; se traduce para el resto del sistema
_TRADUCCION = {
    "Anger": "enojo",
    "Contempt": "desprecio",
    "Disgust": "disgusto",
    "Fear": "miedo",
    "Happiness": "felicidad",
    "Neutral": "neutral",
    "Sadness": "tristeza",
    "Surprise": "sorpresa",
}
EMOCIONES_NEGATIVAS = {"enojo", "disgusto", "desprecio"}


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

    # El recorte debe ser AJUSTADO a la cara (cejas-menton), como las caras con que se entreno
    # el modelo: con 3.4x la separacion de ojos (antes) entraba pelo, cuello y fondo, la cara
    # quedaba chica dentro del recorte y el modelo solo "veia" gestos muy exagerados.
    if confianzas[OJO_IZQ] >= confianza_minima and confianzas[OJO_DER] >= confianza_minima:
        separacion_ojos = np.linalg.norm(keypoints[OJO_IZQ] - keypoints[OJO_DER])
        lado = separacion_ojos * 2.4  # ancho de cara ~2.2-2.5x la distancia entre ojos
    else:
        escala = ancho_hombros(keypoints, confianzas, confianza_minima)
        if escala is None:
            return None
        lado = escala * 0.5  # proporcion tipica cara/ancho-de-hombros como respaldo

    lado = max(lado, 40.0)
    alto_frame, ancho_frame = frame_bgr.shape[:2]

    x0 = int(max(0, nariz[0] - lado / 2))
    x1 = int(min(ancho_frame, nariz[0] + lado / 2))
    y0 = int(max(0, nariz[1] - lado * 0.55))  # la nariz no esta al centro vertical de la cara
    y1 = int(min(alto_frame, nariz[1] + lado * 0.55))

    if x1 - x0 < 20 or y1 - y0 < 20:
        return None
    return frame_bgr[y0:y1, x0:x1]


class DetectorEmocion:
    """Reconocedor HSEmotion compartido (singleton) por todas las estaciones."""

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

        logger.info("Cargando modelo de expresion facial HSEmotion: %s", settings.emocion_modelo_hsemotion)
        self._reconocedor = HSEmotionRecognizer(model_name=settings.emocion_modelo_hsemotion)

    def probabilidades(self, recorte_cara_bgr: np.ndarray) -> dict[str, float]:
        """Probabilidad de CADA emocion (no solo la dominante) para el recorte de cara dado:
        permite promediar varios cuadros seguidos y sumar las emociones negativas, en vez de
        exigir que una sola gane por mucho en un solo cuadro."""
        recorte_rgb = np.ascontiguousarray(recorte_cara_bgr[:, :, ::-1])  # el modelo espera RGB
        _etiqueta, probs = self._reconocedor.predict_emotions(recorte_rgb, logits=False)
        return {
            _TRADUCCION[self._reconocedor.idx_to_class[i]]: float(p) for i, p in enumerate(np.ravel(probs))
        }
