"""Consumidores de tracks WebRTC entrantes: uno para video (YOLO) y otro para audio (Whisper).

Ambos se ejecutan como tareas asyncio en background por cada estacion (`MediaStreamTrack.recv()`
se llama en loop). El trabajo pesado de inferencia se delega a un ThreadPoolExecutor para no
bloquear el event loop de FastAPI mientras la GPU procesa.
"""
import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import av
import numpy as np

from app.core.config import settings
from app.core.db import RUTA_CAPTURAS, registrar_alerta, registrar_transcripcion
from app.core.state import bus_alertas, config_tiempo_real, gestor_estaciones, nuevo_evento
from app.services.emocion.detector import EMOCIONES_NEGATIVAS, DetectorEmocion, recortar_cara
from app.services.stt.lenguaje import contiene_lenguaje_inapropiado
from app.services.stt.transcriber import Transcriptor
from app.services.yolo.detector import NARIZ, OJO_DER, OJO_IZQ, DetectorYOLO, LimitadorFPS

logger = logging.getLogger(__name__)

# Pool compartido para no crear un thread nuevo por cada frame/chunk.
# max_workers moderado: la GPU es el cuello de botella real, no la CPU.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="inferencia")

# Whisper corre en su PROPIO pool, separado del de video (YOLO + HSEmotion): con varias
# camaras conectadas, YOLO/emocion mandan varias tareas por segundo al pool compartido, y una
# transcripcion que quede encolada detras de una racha de esas tareas -o que se demore por
# contencion de GPU entre CUDA (torch/YOLO) y CTranslate2 (faster-whisper) en el mismo device-
# puede tardar mucho mas de lo normal. Aislarla evita que el audio dependa de que tan ocupado
# este el pool de video en ese instante.
_executor_audio = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whisper")

# Si transcribir un chunk se queda pegado mas de esto, se descarta y se seguye con el
# siguiente: sin este limite, una sola llamada colgada (ej. deadlock de CUDA entre varios
# runtimes compartiendo la GPU) congela para siempre el bucle de audio de esa estacion -se
# ve como "el audio llego, Whisper empezo a procesar, y ahi se corta todo silenciosamente".
_TIMEOUT_TRANSCRIPCION_SEGUNDOS = 12.0


def _guardar_captura_bgr(estacion_id: str, tipo: str, imagen_bgr: np.ndarray) -> str | None:
    """Guarda en disco una foto (recorte de cara si se pudo ubicar, si no el cuadro completo)
    en el momento exacto de una alerta, para que el supervisor pueda ver que la origino sin
    tener que haber estado mirando la transmision en vivo justo en ese segundo.

    Devuelve la ruta relativa a `RUTA_CAPTURAS` (se guarda asi en la BD), o None si algo falla
    -una captura fallida nunca debe tumbar el pipeline de deteccion de alertas-.
    """
    try:
        import cv2

        ok_jpeg, buffer_jpeg = cv2.imencode(".jpg", imagen_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok_jpeg:
            return None
        return _guardar_captura_bytes(estacion_id, tipo, buffer_jpeg.tobytes())
    except Exception:
        logger.exception("No se pudo guardar captura de alerta para estacion %s", estacion_id)
        return None


def _codificar_snapshot_jpeg(frame_bgr: np.ndarray) -> bytes | None:
    """Corre en el ThreadPoolExecutor (nunca en el event loop): `cv2.imencode` es una llamada
    bloqueante de CPU, y con varias camaras conectadas a la vez, hacerla directamente en el
    loop de asyncio (como se hacia antes) alcanzaba a acumularse lo suficiente para dejar sin
    turno a las corutinas de audio -sintoma reportado como "con varias camaras no llega nada
    de audio a los logs"-, ya que un `await` nunca se cede mientras el CPU esta ocupado en
    codigo sincrono."""
    import cv2

    ok_jpeg, buffer_jpeg = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buffer_jpeg.tobytes() if ok_jpeg else None


def _guardar_captura_bytes(estacion_id: str, tipo: str, jpeg_bytes: bytes) -> str | None:
    try:
        carpeta = RUTA_CAPTURAS / estacion_id
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        nombre = f"{tipo}_{marca}_{uuid.uuid4().hex[:6]}.jpg"
        (carpeta / nombre).write_bytes(jpeg_bytes)
        return f"{estacion_id}/{nombre}"
    except Exception:
        logger.exception("No se pudo escribir captura de alerta en disco para estacion %s", estacion_id)
        return None


async def consumir_video(track, estacion_id: str) -> None:
    """Lee frames del track de video entrante y los pasa a YOLO (y opcionalmente al modelo
    de expresion facial) a tasa limitada."""
    detector = DetectorYOLO()
    detector_emocion = DetectorEmocion() if settings.emocion_habilitada else None
    limitador = LimitadorFPS(settings.yolo_target_fps)
    limitador_snapshot = LimitadorFPS(10.0)  # el panel no necesita mas de ~10fps de miniatura
    loop = asyncio.get_event_loop()

    # Debounce/cooldown para la expresion facial: exige varias detecciones seguidas antes de
    # alertar, para no disparar por un solo frame ruidoso.
    racha_emocion = 0
    ultimo_ts_alerta_emocion = 0.0

    # Deteccion de ausencia: si la camara deja de ver a alguien por mas de
    # `ausencia_umbral_segundos` seguidos, se avisa una vez (no se repite hasta que la persona
    # vuelva y se vuelva a ir, para no inundar el panel con la misma alerta cada pocos segundos).
    ausente_desde: float | None = None
    alerta_ausencia_enviada = False

    while True:
        try:
            frame = await track.recv()  # objeto av.VideoFrame
        except Exception:
            logger.info("Track de video finalizado para estacion %s", estacion_id)
            break

        try:
            frame_bgr_snapshot = frame.to_ndarray(format="bgr24")
        except Exception:
            logger.exception("No se pudo decodificar frame de video de estacion %s", estacion_id)
            continue

        # El snapshot para el panel de supervisor se genera a ~10fps (no a los ~3fps de YOLO,
        # que se veian entrecortados) pero tampoco a la tasa cruda de la camara: codificar un
        # JPEG en el thread-pool sigue costando CPU, y hacerlo 30 veces por segundo POR CAMARA
        # con varias estaciones conectadas a la vez satura el executor compartido con Whisper,
        # dejando la transcripcion sin turno. 10fps ya se ve fluido para un panel de monitoreo.
        if limitador_snapshot.debe_procesar_ahora():
            try:
                jpeg_bytes = await loop.run_in_executor(_executor, _codificar_snapshot_jpeg, frame_bgr_snapshot)
                if jpeg_bytes:
                    gestor_estaciones.actualizar_snapshot(estacion_id, jpeg_bytes)
            except Exception:
                logger.exception("No se pudo generar snapshot JPEG para estacion %s", estacion_id)

        if not limitador.debe_procesar_ahora():
            continue  # se descarta el frame para YOLO: mantiene la VRAM/GPU libre

        try:
            frame_bgr = frame_bgr_snapshot
            ahora = time.monotonic()

            # La inferencia YOLO es bloqueante (CPU/GPU-bound) -> se corre en thread aparte
            resultado = await loop.run_in_executor(_executor, detector.procesar_frame, frame_bgr)

            if resultado["num_personas"] == 0:
                racha_emocion = 0

                if ausente_desde is None:
                    ausente_desde = ahora
                elif not alerta_ausencia_enviada and (ahora - ausente_desde) >= settings.ausencia_umbral_segundos:
                    alerta_ausencia_enviada = True
                    captura_path = await loop.run_in_executor(
                        _executor, _guardar_captura_bgr, estacion_id, "ausencia", frame_bgr
                    )
                    minutos = settings.ausencia_umbral_segundos / 60
                    detalle = f"Sin actividad frente a la cámara desde hace más de {minutos:.0f} minuto(s)"
                    alerta_id = registrar_alerta(estacion_id, detalle, tipo="ausencia", captura_path=captura_path)
                    await bus_alertas.emitir(
                        nuevo_evento(
                            estacion_id,
                            "alerta_ausencia",
                            {
                                "detalle": detalle,
                                "alerta_id": alerta_id,
                                "veredicto": None,
                                "captura_url": f"/api/alertas/{alerta_id}/captura.jpg" if captura_path else None,
                            },
                        )
                    )
                continue

            # Alguien volvio a aparecer: se reinicia el conteo de ausencia para poder avisar de
            # nuevo si se vuelve a ir.
            ausente_desde = None
            alerta_ausencia_enviada = False

            kpts_persona = resultado["keypoints"][0]
            conf_persona = resultado["confianzas"][0]

            if detector_emocion is not None:
                recorte_cara = recortar_cara(
                    frame_bgr, kpts_persona, conf_persona, settings.emocion_confianza_minima_keypoints
                )
                if recorte_cara is None:
                    racha_emocion = 0
                    # DEBUG temporal: si esto sale seguido, el problema es que no se puede
                    # ubicar la cara con confianza (angulo de camara, iluminacion, keypoints
                    # de ojos/nariz poco confiables) -> nunca llega a clasificar expresion.
                    logger.info(
                        "[debug-expresion] estacion %s: no se pudo ubicar la cara en este frame "
                        "(confianza nariz=%.2f, ojo_izq=%.2f, ojo_der=%.2f, minima requerida=%.2f)",
                        estacion_id, conf_persona[NARIZ] if len(conf_persona) > NARIZ else -1,
                        conf_persona[OJO_IZQ] if len(conf_persona) > OJO_IZQ else -1,
                        conf_persona[OJO_DER] if len(conf_persona) > OJO_DER else -1,
                        settings.emocion_confianza_minima_keypoints,
                    )
                else:
                    etiqueta, probabilidad = await loop.run_in_executor(
                        _executor, detector_emocion.clasificar, recorte_cara
                    )
                    # DEBUG temporal: muestra la clasificacion aunque no cruce el umbral, para
                    # ver si el modelo si esta corriendo y que tan cerca/lejos esta de alertar.
                    logger.info(
                        "[debug-expresion] estacion %s: cara detectada, etiqueta=%s prob=%.2f "
                        "(umbral=%.2f, racha=%d/%d)",
                        estacion_id, etiqueta, probabilidad, settings.emocion_umbral_probabilidad,
                        racha_emocion, settings.emocion_frames_consecutivos,
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
                        # `recorte_cara` es justo el que uso el clasificador para esta alerta:
                        # es la foto mas relevante posible (la cara en el momento exacto del gesto).
                        captura_path = await loop.run_in_executor(
                            _executor, _guardar_captura_bgr, estacion_id, "expresion", recorte_cara
                        )
                        alerta_id = registrar_alerta(estacion_id, detalle, tipo="expresion", captura_path=captura_path)
                        await bus_alertas.emitir(
                            nuevo_evento(
                                estacion_id,
                                "alerta_expresion",
                                {
                                    "detalle": detalle,
                                    "alerta_id": alerta_id,
                                    "veredicto": None,
                                    "captura_url": f"/api/alertas/{alerta_id}/captura.jpg" if captura_path else None,
                                },
                            )
                        )
        except Exception:
            # Un frame problematico (pose incompleta, error puntual de inferencia, etc.) no
            # debe tumbar la tarea completa: sin este try/except, una excepcion aqui mata
            # `consumir_video` para siempre y la estacion deja de generar alertas hasta reconectar.
            logger.exception("Error procesando frame de video de estacion %s", estacion_id)
            racha_emocion = 0


async def consumir_audio(track, estacion_id: str) -> None:
    """Acumula audio y lo envia a Whisper cuando detecta una pausa real de habla, no a un
    tiempo fijo -cortar a horario arbitrario parte frases por la mitad ("...esto es una
    prueba de text" + "o" en el siguiente chunk), lo cual ademas empeora la transcripcion
    porque Whisper pierde el contexto de la frase completa.
    """
    logger.info("[debug-audio] estacion %s: consumir_audio() arranco, esperando frames...", estacion_id)
    transcriptor = Transcriptor()
    loop = asyncio.get_event_loop()

    sample_rate_objetivo = 16000
    # El navegador entrega audio tipicamente a 48kHz; sin resamplear de verdad a 16kHz,
    # Whisper recibe el audio "acelerado" ~3x y su VAD lo confunde con silencio/ruido.
    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate_objetivo)

    muestras_maximas = int(settings.audio_chunk_maximo_segundos * sample_rate_objetivo)
    muestras_minimas = int(settings.audio_chunk_minimo_segundos * sample_rate_objetivo)
    muestras_silencio_para_cortar = int(settings.audio_silencio_para_cortar_ms / 1000 * sample_rate_objetivo)

    buffer: list[np.ndarray] = []
    muestras_acumuladas = 0
    muestras_silencio_consecutivas = 0
    contador_frames_crudos = 0

    while True:
        try:
            frame = await track.recv()  # objeto av.AudioFrame
        except Exception:
            logger.info("Track de audio finalizado para estacion %s", estacion_id)
            break

        contador_frames_crudos += 1
        if contador_frames_crudos <= 3 or contador_frames_crudos % 100 == 0:
            # DEBUG temporal: si esto NUNCA sale, el track de audio no esta llegando (problema
            # de negociacion WebRTC/mic, no de Whisper). Si sale, el audio si esta llegando y
            # el problema esta mas adelante (energia/duracion/Whisper).
            logger.info(
                "[debug-audio] estacion %s: frame crudo #%d recibido (samples=%d, rate=%d)",
                estacion_id, contador_frames_crudos, frame.samples, frame.sample_rate,
            )

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

            energia_frame = float(np.sqrt(np.mean(np.square(audio_np))))
            if energia_frame < settings.audio_silencio_rms:
                muestras_silencio_consecutivas += audio_np.shape[-1]
            else:
                muestras_silencio_consecutivas = 0

        hubo_pausa = (
            muestras_acumuladas >= muestras_minimas
            and muestras_silencio_consecutivas >= muestras_silencio_para_cortar
        )
        alcanzo_tope = muestras_acumuladas >= muestras_maximas
        if not (hubo_pausa or alcanzo_tope):
            continue

        chunk = np.concatenate(buffer)
        buffer.clear()
        muestras_acumuladas = 0
        muestras_silencio_consecutivas = 0

        # DEBUG temporal: energia RMS del chunk completo. Si sale siempre muy por debajo de
        # `audio_energia_minima` (0.01 por defecto), el microfono esta llegando casi en
        # silencio (nivel de captura muy bajo, mic equivocado, o el track de audio no trae
        # nada real) y por eso nunca se manda nada a Whisper.
        energia_chunk = float(np.sqrt(np.mean(np.square(chunk))))
        logger.info(
            "[debug-audio] estacion %s: chunk de %.2fs, energia RMS=%.4f (minima para transcribir=%.4f)",
            estacion_id, len(chunk) / sample_rate_objetivo, energia_chunk, settings.audio_energia_minima,
        )

        inicio_transcripcion = time.monotonic()
        try:
            texto = await asyncio.wait_for(
                loop.run_in_executor(_executor_audio, transcriptor.transcribir_chunk, chunk),
                timeout=_TIMEOUT_TRANSCRIPCION_SEGUNDOS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[debug-audio] estacion %s: Whisper tardo mas de %.0fs transcribiendo un chunk de %.2fs, "
                "se descarta y se sigue con el siguiente (posible contencion de GPU)",
                estacion_id, _TIMEOUT_TRANSCRIPCION_SEGUNDOS, len(chunk) / sample_rate_objetivo,
            )
            continue
        except Exception:
            logger.exception("Error al transcribir audio de estacion %s", estacion_id)
            continue

        logger.info(
            "[debug-audio] estacion %s: texto transcrito en %.2fs = %r",
            estacion_id, time.monotonic() - inicio_transcripcion, texto,
        )

        if not texto:
            continue

        registrar_transcripcion(estacion_id, texto)
        await bus_alertas.emitir(nuevo_evento(estacion_id, "transcripcion", {"texto": texto}))

        deteccion = contiene_lenguaje_inapropiado(texto, nivel=config_tiempo_real.sensibilidad_lenguaje)
        if deteccion:
            categoria_deteccion, texto_detectado = deteccion
            # El detalle guardado en BD conserva la transcripcion completa (auditoria); el
            # que se muestra en vivo va corto, para no llenar el panel con frases largas.
            fragmento = texto if len(texto) <= 60 else texto[:57] + "..."

            # Aqui no hay un frame de video a mano (este pipeline es solo audio): se reusa
            # el ultimo snapshot JPEG que ya genera `consumir_video` en paralelo para la
            # miniatura del panel -es de hace como maximo ~1/yolo_target_fps segundos-.
            info_estacion = gestor_estaciones.obtener(estacion_id)
            captura_path = None
            if info_estacion is not None and info_estacion.ultimo_snapshot_jpeg is not None:
                captura_path = await loop.run_in_executor(
                    _executor, _guardar_captura_bytes, estacion_id, "lenguaje", info_estacion.ultimo_snapshot_jpeg
                )

            etiqueta_deteccion = "Grosería" if categoria_deteccion == "grosería" else "Mal trato"
            alerta_id = registrar_alerta(
                estacion_id,
                f'{etiqueta_deteccion} ("{texto_detectado}") en: "{texto}"',
                tipo="lenguaje",
                captura_path=captura_path,
            )
            await bus_alertas.emitir(
                nuevo_evento(
                    estacion_id,
                    "alerta_lenguaje",
                    {
                        "detalle": f'{etiqueta_deteccion}: "{texto_detectado}" — "{fragmento}"',
                        "alerta_id": alerta_id,
                        "veredicto": None,
                        "captura_url": f"/api/alertas/{alerta_id}/captura.jpg" if captura_path else None,
                    },
                )
            )
