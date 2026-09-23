"""Consumidores de tracks WebRTC entrantes: uno para video (YOLO) y otro para audio (Whisper).

Ambos se ejecutan como tareas asyncio en background por cada estacion (`MediaStreamTrack.recv()`
se llama en loop). El trabajo pesado de inferencia se delega a un ThreadPoolExecutor para no
bloquear el event loop de FastAPI mientras la GPU procesa.
"""
import asyncio
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import av
import numpy as np

from app.core.config import settings
from app.core.db import registrar_alerta
from app.core.state import bus_alertas, nuevo_evento
from app.services.emocion.detector import EMOCIONES_NEGATIVAS, DetectorEmocion, recortar_cara
from app.services.stt.lenguaje import contiene_lenguaje_inapropiado
from app.services.stt.transcriber import Transcriptor
from app.services.yolo.detector import DetectorYOLO, LimitadorFPS, detectar_movimiento_por_ventana

logger = logging.getLogger(__name__)

# Pool compartido para no crear un thread nuevo por cada frame/chunk.
# max_workers moderado: la GPU es el cuello de botella real, no la CPU.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="inferencia")


async def consumir_video(track, estacion_id: str) -> None:
    """Lee frames del track de video entrante y los pasa a YOLO (y opcionalmente al modelo
    de expresion facial) a tasa limitada."""
    detector = DetectorYOLO()
    detector_emocion = DetectorEmocion() if settings.emocion_habilitada else None
    limitador = LimitadorFPS(settings.yolo_target_fps)
    loop = asyncio.get_event_loop()

    # Ventana deslizante de los ultimos N frames (keypoints, confianzas) por estacion:
    # detectar_movimiento_por_ventana promedia sus dos mitades en vez de comparar 2 frames
    # crudos, lo que amortigua el ruido normal de la estimacion de pose.
    historial: deque[tuple[np.ndarray, np.ndarray]] = deque(maxlen=settings.yolo_ventana_frames)
    ultimo_ts_alerta = 0.0

    # Debounce/cooldown independientes para la expresion facial (misma logica que postura,
    # pero por separado: son heuristicas distintas con umbrales distintos).
    racha_emocion = 0
    ultimo_ts_alerta_emocion = 0.0

    while True:
        try:
            frame = await track.recv()  # objeto av.VideoFrame
        except Exception:
            logger.info("Track de video finalizado para estacion %s", estacion_id)
            break

        if not limitador.debe_procesar_ahora():
            continue  # se descarta el frame: mantiene la VRAM/GPU libre

        try:
            frame_bgr = frame.to_ndarray(format="bgr24")

            # La inferencia YOLO es bloqueante (CPU/GPU-bound) -> se corre en thread aparte
            resultado = await loop.run_in_executor(_executor, detector.procesar_frame, frame_bgr)

            if resultado["num_personas"] == 0:
                historial.clear()
                racha_emocion = 0
                continue

            kpts_persona = resultado["keypoints"][0]
            conf_persona = resultado["confianzas"][0]
            historial.append((kpts_persona, conf_persona))

            ahora = time.monotonic()
            cooldown_cumplido = (ahora - ultimo_ts_alerta) >= settings.yolo_alerta_cooldown_segundos
            if cooldown_cumplido and detectar_movimiento_por_ventana(list(historial)):
                ultimo_ts_alerta = ahora
                historial.clear()  # evita que la misma racha de movimiento dispare dos alertas seguidas

                alerta_id = registrar_alerta(estacion_id, "Movimiento brusco detectado")
                await bus_alertas.emitir(
                    nuevo_evento(
                        estacion_id,
                        "alerta_postura",
                        {"detalle": "Movimiento brusco detectado", "alerta_id": alerta_id, "veredicto": None},
                    )
                )

            if detector_emocion is not None:
                recorte_cara = recortar_cara(
                    frame_bgr, kpts_persona, conf_persona, settings.emocion_confianza_minima_keypoints
                )
                if recorte_cara is None:
                    racha_emocion = 0
                else:
                    etiqueta, probabilidad = await loop.run_in_executor(
                        _executor, detector_emocion.clasificar, recorte_cara
                    )
                    if etiqueta in EMOCIONES_NEGATIVAS and probabilidad >= settings.emocion_umbral_probabilidad:
                        racha_emocion += 1
                    else:
                        racha_emocion = 0

                    cooldown_emocion_cumplido = (
                        ahora - ultimo_ts_alerta_emocion
                    ) >= settings.emocion_cooldown_segundos
                    if racha_emocion >= settings.emocion_frames_consecutivos and cooldown_emocion_cumplido:
                        ultimo_ts_alerta_emocion = ahora
                        racha_emocion = 0

                        detalle = f"Expresión facial: {etiqueta} ({probabilidad:.0%})"
                        alerta_id = registrar_alerta(estacion_id, detalle, tipo="expresion")
                        await bus_alertas.emitir(
                            nuevo_evento(
                                estacion_id,
                                "alerta_expresion",
                                {"detalle": detalle, "alerta_id": alerta_id, "veredicto": None},
                            )
                        )
        except Exception:
            # Un frame problematico (pose incompleta, error puntual de inferencia, etc.) no
            # debe tumbar la tarea completa: sin este try/except, una excepcion aqui mata
            # `consumir_video` para siempre y la estacion deja de generar alertas hasta reconectar.
            logger.exception("Error procesando frame de video de estacion %s", estacion_id)
            historial.clear()
            racha_emocion = 0


async def consumir_audio(track, estacion_id: str) -> None:
    """Acumula audio en chunks de N segundos y los envia a Whisper para transcribir."""
    transcriptor = Transcriptor()
    loop = asyncio.get_event_loop()

    sample_rate_objetivo = 16000
    # El navegador entrega audio tipicamente a 48kHz; sin resamplear de verdad a 16kHz,
    # Whisper recibe el audio "acelerado" ~3x y su VAD lo confunde con silencio/ruido.
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate_objetivo)

    muestras_objetivo = int(settings.audio_chunk_seconds * sample_rate_objetivo)
    buffer: list[np.ndarray] = []
    muestras_acumuladas = 0

    while True:
        try:
            frame = await track.recv()  # objeto av.AudioFrame
        except Exception:
            logger.info("Track de audio finalizado para estacion %s", estacion_id)
            break

        try:
            frames_resampleados = resampler.resample(frame)
        except Exception:
            logger.exception("Error al resamplear audio de estacion %s", estacion_id)
            continue

        for frame_16k in frames_resampleados:
            audio_np = frame_16k.to_ndarray().astype(np.float32) / 32768.0
            if audio_np.ndim > 1:
                audio_np = audio_np.mean(axis=0)  # a mono

            buffer.append(audio_np)
            muestras_acumuladas += audio_np.shape[-1]

        if muestras_acumuladas < muestras_objetivo:
            continue

        chunk = np.concatenate(buffer)
        buffer.clear()
        muestras_acumuladas = 0

        try:
            texto = await loop.run_in_executor(_executor, transcriptor.transcribir_chunk, chunk)
        except Exception:
            logger.exception("Error al transcribir audio de estacion %s", estacion_id)
            continue

        if not texto:
            continue

        await bus_alertas.emitir(nuevo_evento(estacion_id, "transcripcion", {"texto": texto}))

        palabra_detectada = contiene_lenguaje_inapropiado(texto)
        if palabra_detectada:
            # El detalle guardado en BD conserva la transcripcion completa (auditoria); el
            # que se muestra en vivo va corto, para no llenar el panel con frases largas.
            fragmento = texto if len(texto) <= 60 else texto[:57] + "..."
            alerta_id = registrar_alerta(estacion_id, f'Palabra "{palabra_detectada}" en: "{texto}"', tipo="lenguaje")
            await bus_alertas.emitir(
                nuevo_evento(
                    estacion_id,
                    "alerta_lenguaje",
                    {
                        "detalle": f'"{palabra_detectada}" — "{fragmento}"',
                        "alerta_id": alerta_id,
                        "veredicto": None,
                    },
                )
            )
