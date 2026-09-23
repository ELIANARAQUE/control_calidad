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

        Se recomienda VAD (voice activity detection) previo si el chunk suele venir en silencio,
        para no gastar computo en audio vacio; `vad_filter=True` ya lo hace internamente.
        """
        segmentos, _info = self.modelo.transcribe(
            audio_f32_mono_16k,
            language="es",
            vad_filter=True,
            beam_size=1,  # beam pequeno para priorizar latencia sobre precision
        )
        return " ".join(seg.text.strip() for seg in segmentos).strip()
