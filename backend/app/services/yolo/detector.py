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
    """
    if confianzas[HOMBRO_IZQ] < confianza_minima or confianzas[HOMBRO_DER] < confianza_minima:
        return None
    ancho = np.linalg.norm(keypoints[HOMBRO_IZQ] - keypoints[HOMBRO_DER])
    return float(ancho) if ancho > 1e-3 else None


def _promedio_ponderado(
    frames_kpts: list[np.ndarray], frames_conf: list[np.ndarray], idx: int, confianza_minima: float
) -> np.ndarray | None:
    """Promedia la posicion de un keypoint a lo largo de varios frames, usando la confianza
    como peso e ignorando frames donde ese punto no es fiable. Promediar (en vez de comparar
    2 puntos crudos) es lo que amortigua el "temblor" frame a frame de la estimacion de pose.
    """
    puntos, pesos = [], []
    for kpts, conf in zip(frames_kpts, frames_conf):
        if idx < len(kpts) and conf[idx] >= confianza_minima:
            puntos.append(kpts[idx])
            pesos.append(conf[idx])
    if not puntos:
        return None
    return np.average(np.array(puntos), axis=0, weights=np.array(pesos))


def detectar_movimiento_por_ventana(historial: list[tuple[np.ndarray, np.ndarray]]) -> bool:
    """Heuristica de "movimiento brusco" sobre una ventana deslizante de frames.

    En vez de comparar 2 frames crudos (sensible al ruido normal de la pose), se divide la
    ventana en "primera mitad" y "segunda mitad", se promedia la posicion de cada keypoint
    dentro de cada mitad (ponderado por confianza) y se compara el desplazamiento entre esos
    dos promedios. Esto es, en esencia, una estimacion de velocidad suavizada en vez de un
    salto puntual, y normaliza por el ancho de hombros para no depender de la distancia a la
    camara.
    """
    if len(historial) < settings.yolo_ventana_frames:
        return False

    frames_kpts = [k for k, _ in historial]
    frames_conf = [c for _, c in historial]
    mitad = len(historial) // 2
    mitad_vieja_kpts, mitad_vieja_conf = frames_kpts[:mitad], frames_conf[:mitad]
    mitad_nueva_kpts, mitad_nueva_conf = frames_kpts[mitad:], frames_conf[mitad:]

    kpts_actuales, conf_actuales = historial[-1]
    escala = _ancho_hombros(kpts_actuales, conf_actuales, settings.yolo_movimiento_confianza_minima)
    if escala is None:
        return False  # sin referencia de escala fiable, no se puede juzgar "brusco" con seguridad

    puntos_a_comparar = [MUNECA_IZQ, MUNECA_DER, HOMBRO_IZQ, HOMBRO_DER]
    for idx in puntos_a_comparar:
        pos_vieja = _promedio_ponderado(mitad_vieja_kpts, mitad_vieja_conf, idx, settings.yolo_movimiento_confianza_minima)
        pos_nueva = _promedio_ponderado(mitad_nueva_kpts, mitad_nueva_conf, idx, settings.yolo_movimiento_confianza_minima)
        if pos_vieja is None or pos_nueva is None:
            continue  # sin suficientes observaciones fiables de este punto en alguna mitad

        despl_relativo = np.linalg.norm(pos_nueva - pos_vieja) / escala
        if despl_relativo > settings.yolo_movimiento_umbral_relativo:
            return True
    return False
