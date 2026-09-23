"""Configuracion centralizada del servidor. Ajustable via variables de entorno (.env)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- General ---
    app_name: str = "QA Monitor Local"
    max_estaciones_concurrentes: int = 10  # limite duro de conexiones WebRTC activas

    # --- Vision por computador (YOLO) ---
    yolo_model_path: str = "../models/yolov8n-pose.pt"  # modelo de pose, liviano
    yolo_target_fps: float = 3.0  # cuadros por segundo a procesar por camara (2-5 recomendado)
    yolo_device: str = "cuda:0"  # "cpu" si no hay GPU disponible
    yolo_imgsz: int = 480  # resolucion de inferencia reducida para ahorrar VRAM
    yolo_confidence: float = 0.5

    # --- Heuristica de "movimiento brusco" ---
    yolo_movimiento_confianza_minima: float = 0.5  # ignora keypoints poco confiables (jitter de pose)
    yolo_movimiento_umbral_relativo: float = 0.6  # desplazamiento minimo, en "anchos de hombro", para contar como brusco
    yolo_ventana_frames: int = 5  # cuantos frames recientes se mantienen en el buffer de contexto
    yolo_alerta_cooldown_segundos: float = 8.0  # tiempo minimo entre alertas repetidas de la misma estacion

    # --- Expresion facial (FER+) ---
    emocion_habilitada: bool = True
    emocion_modelo_path: str = "../models/emotion-ferplus-8.onnx"
    emocion_confianza_minima_keypoints: float = 0.4  # nariz/ojos suelen tener algo menos de confianza que hombros
    emocion_umbral_probabilidad: float = 0.55  # que tan segura debe estar la clasificacion para contar
    emocion_frames_consecutivos: int = 2  # exige varias detecciones seguidas antes de alertar
    emocion_cooldown_segundos: float = 10.0  # tiempo minimo entre alertas repetidas de la misma estacion

    # --- Audio / STT ---
    whisper_model_size: str = "small"  # tiny/base/small/medium segun VRAM disponible
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"  # cuantizacion para ahorrar VRAM
    audio_chunk_seconds: float = 3.0  # mas corto = menos latencia percibida, pero mas overhead por chunk
    audio_energia_minima: float = 0.01  # RMS minimo para mandar el chunk a Whisper (evita alucinar en silencio)
    whisper_no_speech_prob_maximo: float = 0.45  # descarta segmentos que el propio modelo considera poco fiables

    # --- Rutas ---
    recordings_dir: str = "recordings"

    class Config:
        env_file = ".env"


settings = Settings()
