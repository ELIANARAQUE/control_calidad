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
    "gracias por su atencion",
    "nos vemos en el proximo video",
    "like y suscribete",
    "dale like y suscribete",
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

    def transcribir_chunk(self, audio_f32_mono_16k: np.ndarray) -> str:
        """Recibe audio mono float32 a 16kHz y devuelve el texto transcrito.

        Dos filtros contra las "alucinaciones" tipicas de Whisper en silencio (frases de
        YouTube como "suscribete"): 1) si el chunk no supera un piso de energia, ni se
        manda al modelo; 2) el `vad_filter` interno de faster-whisper recorta los tramos
        sin voz dentro del chunk antes de transcribir.
        """
        energia = float(np.sqrt(np.mean(np.square(audio_f32_mono_16k))))  # RMS
        if energia < settings.audio_energia_minima:
            return ""

        segmentos, _info = self.modelo.transcribe(
            audio_f32_mono_16k,
            language="es",
            vad_filter=True,
            vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 300},
            beam_size=1,  # beam pequeno para priorizar latencia sobre precision
            condition_on_previous_text=False,  # evita que una alucinacion se "contagie" al siguiente chunk
        )
        texto = " ".join(seg.text.strip() for seg in segmentos).strip()

        if texto and _es_alucinacion(texto):
            logger.debug("Descartada probable alucinacion de Whisper: %r", texto)
            return ""

        return texto
