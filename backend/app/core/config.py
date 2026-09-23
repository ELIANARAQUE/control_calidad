"""Configuracion centralizada del servidor. Ajustable via variables de entorno (.env)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- General ---
    app_name: str = "QA Monitor Local"
    max_estaciones_concurrentes: int = 10  # limite duro de conexiones WebRTC activas

    # --- Vision por computador (YOLO) ---
    yolo_model_path: str = "models/yolov8n-pose.pt"  # modelo de pose, liviano
    yolo_target_fps: float = 3.0  # cuadros por segundo a procesar por camara (2-5 recomendado)
    yolo_device: str = "cuda:0"  # "cpu" si no hay GPU disponible
    yolo_imgsz: int = 480  # resolucion de inferencia reducida para ahorrar VRAM
    yolo_confidence: float = 0.5

    # --- Audio / STT ---
    whisper_model_size: str = "small"  # tiny/base/small/medium segun VRAM disponible
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"  # cuantizacion para ahorrar VRAM
    audio_chunk_seconds: float = 4.0

    # --- Rutas ---
    recordings_dir: str = "recordings"

    class Config:
        env_file = ".env"


settings = Settings()
