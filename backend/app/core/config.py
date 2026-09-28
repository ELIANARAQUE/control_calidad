"""Configuracion centralizada del servidor. Ajustable via variables de entorno (.env)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- General ---
    app_name: str = "QA Monitor Local"
    max_estaciones_concurrentes: int = 10  # limite duro de conexiones WebRTC activas

    # --- Supabase (reemplaza la base SQLite local: usuarios, alertas,
    # transcripciones, eventos de conexion, opciones configurables) ---
    # Obligatorios: sin esto el backend no arranca (ver app/core/supabase_client.py).
    # SUPABASE_KEY debe ser la SERVICE ROLE KEY (no la anon key): el backend necesita
    # poder leer/escribir sin las restricciones de Row Level Security de un cliente publico.
    supabase_url: str = ""
    supabase_key: str = ""

    # --- Cifrado de datos sensibles (numero de documento, correo electronico) ---
    # Clave simetrica de `cryptography.fernet.Fernet`. Generar una con:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # y ponerla en .env como FERNET_KEY -si se pierde o se cambia, los datos cifrados
    # existentes ya no se pueden descifrar, asi que hacer backup de esta clave.
    fernet_key: str = ""

    # --- Acceso del panel de supervisor (legado; ver tabla `usuarios` en Supabase) ---
    # Se mantiene por si algun script viejo todavia depende de un admin de respaldo, pero el
    # login real del panel ahora valida contra la tabla `usuarios` (rol='admin') + verificacion
    # facial, no contra estas dos variables.
    admin_usuario: str = "admin"
    admin_clave: str = "admin123"

    # --- Vision por computador (YOLO) ---
    yolo_model_path: str = "../models/yolov8n-pose.pt"  # modelo de pose, liviano
    yolo_target_fps: float = 3.0  # cuadros por segundo a procesar por camara (2-5 recomendado)
    yolo_device: str = "cuda:0"  # "cpu" si no hay GPU disponible
    yolo_imgsz: int = 480  # resolucion de inferencia reducida para ahorrar VRAM
    yolo_confidence: float = 0.5

    # --- Deteccion de ausencia ---
    # Reemplaza la vieja heuristica de "movimiento brusco" (generaba demasiados falsos
    # positivos: moverse en la silla, agacharse a buscar algo, bajar la cabeza a mirar el
    # teclado, todo disparaba alerta). En su lugar, se avisa si la camara deja de ver a
    # alguien durante mucho tiempo seguido (posible abandono del puesto).
    ausencia_umbral_segundos: float = 300.0  # 5 minutos sin detectar a nadie frente a la camara

    # --- Expresion facial (HSEmotion, entrenado sobre AffectNet) ---
    emocion_habilitada: bool = True
    # AffectNet (caras naturales); el anterior "enet_b0_8_best_afew" era de escenas de peliculas
    # actuadas y solo captaba gestos exagerados. Se descarga solo a ~/.hsemotion/ la primera vez.
    emocion_modelo_hsemotion: str = "enet_b2_8"
    emocion_confianza_minima_keypoints: float = 0.4  # nariz/ojos suelen tener algo menos de confianza que hombros
    # Las probabilidades se PROMEDIAN sobre los ultimos N cuadros (suaviza el ruido de un solo
    # cuadro) y se SUMAN las tres emociones negativas: un enojo leve rara vez gana solo frente a
    # "neutral", pero enojo+disgusto+desprecio juntos si reflejan un gesto negativo real.
    emocion_ventana_frames: int = 5
    emocion_umbral_probabilidad: float = 0.35  # suma de probabilidad negativa promediada para alertar
    emocion_frames_consecutivos: int = 3  # cuadros seguidos por encima del umbral antes de alertar
    # Por encima de este puntaje negativo, la alerta es CRITICA: el panel del supervisor abre un
    # modal que le pide gestionarla de inmediato.
    emocion_umbral_critico: float = 0.75
    # Expresiones positivas: felicidad promediada por encima de este valor se registra (solo
    # informativa: no se califica como real/falsa, solo se puede eliminar).
    emocion_umbral_positivo: float = 0.60
    emocion_positiva_cooldown_segundos: float = 30.0
    emocion_cooldown_segundos: float = 10.0  # tiempo minimo entre alertas repetidas de la misma estacion

    # --- Audio / STT ---
    # large-v3-turbo: mucho mas preciso que "small" con ruido/volumen bajo (en pruebas, "small"
    # escribia "hipuecuta" en vez de "hijueputa" y se perdia la groseria) y en la GPU tarda
    # ~0.25 s por frase. Se descarga solo la primera vez (~1.6 GB, a ~/.cache/huggingface).
    whisper_model_size: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    whisper_modelo_cpu: str = "small"  # si la GPU falla, en CPU el modelo grande seria muy lento
    whisper_device: str = "cuda"
    whisper_compute_type: str = "int8_float16"  # cuantizacion para ahorrar VRAM
    whisper_beam_size: int = 5  # busqueda mas amplia = transcripcion mas precisa (con GPU sobra tiempo)
    # Originalmente 14s/900ms, se bajo a 7s/500ms para reducir latencia, pero 500ms resulto
    # demasiado agresivo: una pausa normal al hablar en espaniol (respirar, dudar) ya dura eso,
    # asi que se cortaba la frase a la mitad y el chunk resultante quedaba sin contexto
    # suficiente para que Whisper lo transcribiera bien (a veces ni pasaba el VAD interno).
    # 800ms/10s es un punto medio: sigue siendo mas rapido que el original, pero no corta
    # frases a mitad de una pausa para respirar.
    audio_chunk_maximo_segundos: float = 10.0  # tope duro: si la persona no para de hablar, igual se corta aqui
    audio_chunk_minimo_segundos: float = 0.5  # no vale la pena transcribir chunks mas cortos que esto
    audio_silencio_para_cortar_ms: float = 800.0  # pausa de habla que se interpreta como fin de frase (no una coma)
    audio_energia_minima: float = 0.01  # RMS minimo para mandar el chunk a Whisper (evita alucinar en silencio)
    audio_silencio_rms: float = 0.006  # RMS por debajo del cual un frame cuenta como "silencio" para cortar
    whisper_no_speech_prob_maximo: float = 0.45  # descarta segmentos que el propio modelo considera poco fiables

    # --- Rutas ---
    recordings_dir: str = "recordings"

    class Config:
        env_file = ".env"


settings = Settings()
