"""Consumidores de tracks WebRTC entrantes: uno para video (YOLO) y otro para audio (Whisper).

Ambos se ejecutan como tareas asyncio en background por cada estacion (`MediaStreamTrack.recv()`
se llama en loop). El trabajo pesado de inferencia se delega a un ThreadPoolExecutor para no
bloquear el event loop de FastAPI mientras la GPU procesa.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app.core.config import settings
from app.core.state import bus_alertas, nuevo_evento
from app.services.stt.transcriber import Transcriptor
from app.services.yolo.detector import DetectorYOLO, LimitadorFPS, detectar_movimiento_brusco

logger = logging.getLogger(__name__)

# Pool compartido para no crear un thread nuevo por cada frame/chunk.
# max_workers moderado: la GPU es el cuello de botella real, no la CPU.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="inferencia")


async def consumir_video(track, estacion_id: str) -> None:
    """Lee frames del track de video entrante y los pasa a YOLO a tasa limitada."""
    detector = DetectorYOLO()
    limitador = LimitadorFPS(settings.yolo_target_fps)
    keypoints_previos = None
    loop = asyncio.get_event_loop()

    while True:
        try:
            frame = await track.recv()  # objeto av.VideoFrame
        except Exception:
            logger.info("Track de video finalizado para estacion %s", estacion_id)
            break

        if not limitador.debe_procesar_ahora():
            continue  # se descarta el frame: mantiene la VRAM/GPU libre

        frame_bgr = frame.to_ndarray(format="bgr24")

        # La inferencia YOLO es bloqueante (CPU/GPU-bound) -> se corre en thread aparte
        resultado = await loop.run_in_executor(_executor, detector.procesar_frame, frame_bgr)

        if resultado["num_personas"] == 0:
            keypoints_previos = None
            continue

        kpts_actuales = resultado["keypoints"][0]
        if detectar_movimiento_brusco(keypoints_previos, kpts_actuales):
            await bus_alertas.emitir(
                nuevo_evento(estacion_id, "alerta_postura", {"detalle": "Movimiento brusco detectado"})
            )
        keypoints_previos = kpts_actuales


async def consumir_audio(track, estacion_id: str) -> None:
    """Acumula audio en chunks de N segundos y los envia a Whisper para transcribir."""
    transcriptor = Transcriptor()
    loop = asyncio.get_event_loop()

    sample_rate_objetivo = 16000
    muestras_objetivo = int(settings.audio_chunk_seconds * sample_rate_objetivo)
    buffer: list[np.ndarray] = []
    muestras_acumuladas = 0

    while True:
        try:
            frame = await track.recv()  # objeto av.AudioFrame
        except Exception:
            logger.info("Track de audio finalizado para estacion %s", estacion_id)
            break

        # Resamplear a 16kHz mono si el frame entrante viene en otra tasa/canal
        audio_np = frame.to_ndarray().astype(np.float32) / 32768.0
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=0)  # a mono

        buffer.append(audio_np)
        muestras_acumuladas += audio_np.shape[-1]

        if muestras_acumuladas < muestras_objetivo:
            continue

        chunk = np.concatenate(buffer)
        buffer.clear()
        muestras_acumuladas = 0

        texto = await loop.run_in_executor(_executor, transcriptor.transcribir_chunk, chunk)
        if texto:
            await bus_alertas.emitir(
                nuevo_evento(estacion_id, "transcripcion", {"texto": texto})
            )
