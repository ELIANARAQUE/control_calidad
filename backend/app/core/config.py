"""Configuracion centralizada del servidor. Ajustable via variables de entorno (.env)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- General ---
    app_name: str = "QA Monitor Local"
    max_estaciones_concurrentes: int = 10  # limite duro de conexiones WebRTC activas

    # --- Acceso del panel de supervisor ---
    # Pensado para una red local cerrada: un usuario/clave compartido es suficiente para
    # evitar que cualquiera en la red abra el panel, sin necesitar un sistema de cuentas.
    # Ajustable via .env (ADMIN_USUARIO / ADMIN_CLAVE) para no dejar el valor por defecto en produccion.
    admin_usuario: str = "admin"
    admin_clave: str = "admin123"

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

    # --- Expresion facial (HSEmotion, entrenado sobre AffectNet) ---
    emocion_habilitada: bool = True
    emocion_modelo_hsemotion: str = "enet_b0_8_best_afew"  # se descarga solo a ~/.hsemotion/ la primera vez
    emocion_confianza_minima_keypoints: float = 0.4  # nariz/ojos suelen tener algo menos de confianza que hombros
    emocion_umbral_probabilidad: float = 0.4  # HSEmotion tiende a repartir mas probabilidad entre clases que FER+
    emocion_frames_consecutivos: int = 2  # exige varias detecciones seguidas antes de alertar
    emocion_cooldown_segundos: float = 10.0  # tiempo minimo entre alertas repetidas de la misma estacion

    # --- Audio / STT ---
    # Con GPU, "small" da buena precision sin ser lento. Si algun dia se corre sin GPU
    # (WHISPER_DEVICE=cpu en .env), bajar esto a "base" o "tiny" es la palanca de mayor
    # impacto para recuperar velocidad.
    whisper_model_size: str = "small"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"  # cuantizacion para ahorrar VRAM
    # Antes eran 14s/900ms: con audio continuo (sin pausas claras) el empleado y el supervisor
    # esperaban hasta 14 segundos a ver el texto. Bajar el tope duro y el silencio de corte
    # hace que la transcripcion "salga" con mucha mas frecuencia, al costo de partir frases
    # largas en 2 chunks mas seguido (Whisper igual las transcribe bien por separado).
    audio_chunk_maximo_segundos: float = 7.0  # tope duro: si la persona no para de hablar, igual se corta aqui
    audio_chunk_minimo_segundos: float = 0.5  # no vale la pena transcribir chunks mas cortos que esto
    audio_silencio_para_cortar_ms: float = 500.0  # pausa de habla que se interpreta como fin de frase (no una coma)
    audio_energia_minima: float = 0.01  # RMS minimo para mandar el chunk a Whisper (evita alucinar en silencio)
    audio_silencio_rms: float = 0.006  # RMS por debajo del cual un frame cuenta como "silencio" para cortar
    whisper_no_speech_prob_maximo: float = 0.45  # descarta segmentos que el propio modelo considera poco fiables

    # --- Rutas ---
    recordings_dir: str = "recordings"

    class Config:
        env_file = ".env"


settings = Settings()
