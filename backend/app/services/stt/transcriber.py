"""Wrapper de faster-whisper para transcribir chunks de audio de 3-5 segundos.

faster-whisper (CTranslate2) es preferible a whisper "vanilla" aqui porque:
  - Usa mucha menos VRAM para el mismo modelo (cuantizacion int8/float16).
  - Es mas rapido en CPU tambien, por si el servidor se queda sin GPU libre.
"""
import logging

import numpy as np
from faster_whisper import WhisperModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# Frases que Whisper "alucina" tipicamente cuando el audio esta en silencio o casi silencio
# (viene de haber sido entrenado con muchisimo video de YouTube). No son transcripciones
# reales: se descartan aunque el chunk pase el filtro de energia.
FRASES_ALUCINACION = {
    "suscribete",
    "suscribete al canal",
    "gracias por ver el video",
    "gracias por ver",
    "gracias por ver este video",
    "gracias por su atencion",
    "gracias por verme",
    "muchas gracias",
    "nos vemos en el proximo video",
    "nos vemos en el siguiente video",
    "hasta el proximo video",
    "like y suscribete",
    "dale like y suscribete",
    "activa la campanita",
    "cuidate",
    "cuidense",
    "care onda",
    "chao",
    "adios",
}


def _normalizar(texto: str) -> str:
    import unicodedata

    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_tildes.lower().strip(" ¡!¿?.")


def _es_alucinacion(texto: str) -> bool:
    return _normalizar(texto) in FRASES_ALUCINACION


class Transcriptor:
    """Modelo Whisper compartido (singleton) por todas las estaciones de audio."""

    _instancia: "Transcriptor | None" = None

    def __new__(cls) -> "Transcriptor":
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self) -> None:
        if self._inicializado:
            return
        self._inicializado = True

        logger.info("Cargando modelo Whisper: %s (device=%s)", settings.whisper_model_size, settings.whisper_device)
        self.modelo = WhisperModel(
            settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        # `WhisperModel(...)` no falla aunque CUDA no funcione de verdad (torch puede reportar
        # GPU disponible via nvidia-smi sin que el proceso de Python tenga las librerias CUDA
        # que CTranslate2 necesita, ej. "cublas64_12.dll is not found"): el error solo aparece
        # en el primer `.transcribe()`. Por eso el fallback a CPU vive en `transcribir_chunk`,
        # no aqui.
        self._forzado_a_cpu = False

    def _recargar_en_cpu(self) -> None:
        logger.warning(
            "Whisper con device=%s fallo al transcribir (ver traceback arriba, tipicamente "
            "falta una libreria CUDA como cublas/cuDNN aunque haya GPU en la maquina). "
            "Recargando el modelo en CPU para que el sistema siga funcionando -sera mas lento, "
            "pero deja de romperse en cada chunk-.",
            settings.whisper_device,
        )
        self.modelo = WhisperModel(settings.whisper_model_size, device="cpu", compute_type="int8")
        self._forzado_a_cpu = True

    def transcribir_chunk(self, audio_f32_mono_16k: np.ndarray) -> str:
        """Recibe audio mono float32 a 16kHz y devuelve el texto transcrito.

        Filtros contra las "alucinaciones" tipicas de Whisper en silencio/ruido de fondo
        (frases de YouTube como "suscribete" o "nos vemos en el proximo video"):
          1. Piso de energia: si el chunk no supera un RMS minimo, ni se manda al modelo.
          2. `vad_filter` interno de faster-whisper recorta los tramos sin voz del chunk.
          3. El propio `no_speech_prob` que da Whisper por segmento: es la probabilidad,
             segun el modelo, de que ESE segmento no tenga voz humana real. Las alucinaciones
             tipicamente salen con `no_speech_prob` alto (el modelo "no esta seguro" pero
             igual rellena texto), asi que es mucho mas confiable que una lista de frases.
          4. Lista negra de frases conocidas, como ultimo filtro por si aun asi se cuela algo.
        """
        energia = float(np.sqrt(np.mean(np.square(audio_f32_mono_16k))))  # RMS
        if energia < settings.audio_energia_minima:
            return ""

        try:
            segmentos, _info = self.modelo.transcribe(
                audio_f32_mono_16k,
                language="es",
                vad_filter=True,
                vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 300},
                beam_size=1,  # beam pequeno para priorizar latencia sobre precision
                condition_on_previous_text=False,  # evita que una alucinacion se "contagie" al siguiente chunk
            )
            segmentos = list(segmentos)  # fuerza la evaluacion aqui, dentro del try
        except RuntimeError:
            if self._forzado_a_cpu:
                raise  # ya estamos en CPU: esto es un error real, no lo escondas
            logger.exception("Fallo transcribiendo con device=%s", settings.whisper_device)
            self._recargar_en_cpu()
            segmentos, _info = self.modelo.transcribe(
                audio_f32_mono_16k,
                language="es",
                vad_filter=True,
                vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 300},
                beam_size=1,
                condition_on_previous_text=False,
            )

        partes_confiables = [
            seg.text.strip()
            for seg in segmentos
            if seg.no_speech_prob < settings.whisper_no_speech_prob_maximo
        ]
        texto = " ".join(p for p in partes_confiables if p).strip()

        if texto and _es_alucinacion(texto):
            logger.debug("Descartada probable alucinacion de Whisper: %r", texto)
            return ""

        return texto
