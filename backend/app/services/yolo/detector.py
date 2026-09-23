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
        for r in resultados:
            if r.keypoints is None:
                continue
            for kpts in r.keypoints.xy.cpu().numpy():
                personas.append(kpts)

        return {
            "num_personas": len(personas),
            "keypoints": personas,
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


def detectar_movimiento_brusco(keypoints_previos: np.ndarray, keypoints_actuales: np.ndarray, umbral_px: float = 60.0) -> bool:
    """Heuristica simple: distancia euclidiana entre munecas/hombros de un frame al siguiente."""
    if keypoints_previos is None or keypoints_actuales is None:
        return False
    puntos_a_comparar = [MUNECA_IZQ, MUNECA_DER, HOMBRO_IZQ, HOMBRO_DER]
    for idx in puntos_a_comparar:
        if idx >= len(keypoints_previos) or idx >= len(keypoints_actuales):
            continue
        despl = np.linalg.norm(keypoints_actuales[idx] - keypoints_previos[idx])
        if despl > umbral_px:
            return True
    return False
