"""Wrapper de YOLO (Ultralytics) para deteccion de poses/gestos, optimizado para VRAM compartida.

Puntos clave para no saturar la GPU con 5-10 camaras concurrentes:
  1. Un unico modelo cargado en memoria, compartido por todas las estaciones (no uno por camara).
  2. Inferencia limitada a `yolo_target_fps` por camara (se descartan los cuadros de mas).
  3. Resolucion de entrada reducida (`yolo_imgsz`).
  4. `torch.inference_mode()` + half precision en GPU para reducir uso de memoria.
"""
import logging
import time

import numpy as np
import torch
from ultralytics import YOLO

from app.core.config import settings

logger = logging.getLogger(__name__)

# Indices de keypoints COCO-pose relevantes para detectar movimientos bruscos
NARIZ, HOMBRO_IZQ, HOMBRO_DER, MUNECA_IZQ, MUNECA_DER = 0, 5, 6, 9, 10


class DetectorYOLO:
    """Carga el modelo una sola vez (patron singleton) y expone `procesar_frame`."""

    _instancia: "DetectorYOLO | None" = None

    def __new__(cls) -> "DetectorYOLO":
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self) -> None:
        if self._inicializado:
            return
        self._inicializado = True

        logger.info("Cargando modelo YOLO: %s (device=%s)", settings.yolo_model_path, settings.yolo_device)
        self.device = settings.yolo_device if torch.cuda.is_available() else "cpu"
        self.modelo = YOLO(settings.yolo_model_path)
        self.modelo.to(self.device)
        self.usa_fp16 = self.device.startswith("cuda")

    @torch.inference_mode()
    def procesar_frame(self, frame_bgr: np.ndarray) -> dict:
        """Ejecuta la deteccion sobre un frame y devuelve keypoints + posibles alertas.

        `frame_bgr`: array numpy HxWx3 en formato BGR (el que entrega OpenCV/aiortc).
        """
        resultados = self.modelo.predict(
            source=frame_bgr,
            imgsz=settings.yolo_imgsz,
            conf=settings.yolo_confidence,
            device=self.device,
            half=self.usa_fp16,
            verbose=False,
        )

        personas = []
        confianzas = []
        for r in resultados:
            if r.keypoints is None:
                continue
            xy = r.keypoints.xy.cpu().numpy()
            # `.conf` puede venir None si el modelo no expone confianza por punto
            conf = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(xy.shape[:2])
            for kpts, kconf in zip(xy, conf):
                personas.append(kpts)
                confianzas.append(kconf)

        return {
            "num_personas": len(personas),
            "keypoints": personas,
            "confianzas": confianzas,
        }


class LimitadorFPS:
    """Controla que una camara no se procese mas rapido que `yolo_target_fps`."""

    def __init__(self, fps_objetivo: float = settings.yolo_target_fps) -> None:
        self.intervalo = 1.0 / fps_objetivo
        self._ultimo_ts = 0.0

    def debe_procesar_ahora(self) -> bool:
        ahora = time.monotonic()
        if ahora - self._ultimo_ts >= self.intervalo:
            self._ultimo_ts = ahora
            return True
        return False


def _ancho_hombros(keypoints: np.ndarray, confianzas: np.ndarray, confianza_minima: float) -> float | None:
    """Distancia en pixeles entre hombros: sirve como referencia de escala de la persona
    (mas cerca de la camara = hombros mas separados en pixeles = umbral de movimiento mayor).

    Puede no haber keypoints en absoluto para esta persona en este frame (ej. YOLO detecto
    la caja pero no pudo estimar la pose), de ahi el chequeo de longitud antes de indexar.
    """
    if len(confianzas) <= max(HOMBRO_IZQ, HOMBRO_DER) or len(keypoints) <= max(HOMBRO_IZQ, HOMBRO_DER):
        return None
    if confianzas[HOMBRO_IZQ] < confianza_minima or confianzas[HOMBRO_DER] < confianza_minima:
        return None
    ancho = np.linalg.norm(keypoints[HOMBRO_IZQ] - keypoints[HOMBRO_DER])
    return float(ancho) if ancho > 1e-3 else None


def _hay_movimiento_entre_frames(
    kpts_prev: np.ndarray, conf_prev: np.ndarray, kpts_act: np.ndarray, conf_act: np.ndarray, escala: float
) -> bool:
    puntos_a_comparar = [MUNECA_IZQ, MUNECA_DER, HOMBRO_IZQ, HOMBRO_DER]
    for idx in puntos_a_comparar:
        if idx >= len(kpts_prev) or idx >= len(kpts_act) or idx >= len(conf_prev) or idx >= len(conf_act):
            continue
        if conf_prev[idx] < settings.yolo_movimiento_confianza_minima or conf_act[idx] < settings.yolo_movimiento_confianza_minima:
            continue  # punto poco fiable en alguno de los dos frames: se ignora
        despl_relativo = np.linalg.norm(kpts_act[idx] - kpts_prev[idx]) / escala
        if despl_relativo > settings.yolo_movimiento_umbral_relativo:
            return True
    return False


def detectar_movimiento_por_ventana(historial: list[tuple[np.ndarray, np.ndarray]]) -> bool:
    """Heuristica de "movimiento brusco" sobre una ventana deslizante de frames.

    Recorre pares de frames consecutivos dentro de la ventana buscando un desplazamiento
    brusco (normalizado por el ancho de hombros, para no depender de la distancia a la
    camara). Exige que el desplazamiento se sostenga por 2 pares consecutivos -para filtrar
    el ruido de un solo frame- pero, a diferencia de promediar toda la ventana, SI reacciona
    a un gesto breve aunque la persona vuelva enseguida a su posicion de reposo (ej. una
    mala cara momentanea) en vez de que el promedio la "cancele".
    """
    racha = 0
    for i in range(1, len(historial)):
        kpts_prev, conf_prev = historial[i - 1]
        kpts_act, conf_act = historial[i]

        escala = _ancho_hombros(kpts_act, conf_act, settings.yolo_movimiento_confianza_minima)
        if escala is None:
            racha = 0
            continue

        if _hay_movimiento_entre_frames(kpts_prev, conf_prev, kpts_act, conf_act, escala):
            racha += 1
            if racha >= 2:
                return True
        else:
            racha = 0
    return False
