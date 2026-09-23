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
    yolo_movimiento_umbral_relativo: float = 0.8  # desplazamiento minimo, en "anchos de hombro", para contar como brusco
    yolo_ventana_frames: int = 5  # tamano de la ventana deslizante (a 3 FPS ~ 1.5-2s de contexto)
    yolo_alerta_cooldown_segundos: float = 8.0  # tiempo minimo entre alertas repetidas de la misma estacion

    # --- Audio / STT ---
    whisper_model_size: str = "small"  # tiny/base/small/medium segun VRAM disponible
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"  # cuantizacion para ahorrar VRAM
    audio_chunk_seconds: float = 4.0
    audio_energia_minima: float = 0.01  # RMS minimo para mandar el chunk a Whisper (evita alucinar en silencio)

    # --- Rutas ---
    recordings_dir: str = "recordings"

    class Config:
        env_file = ".env"


settings = Settings()
