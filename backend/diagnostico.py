"""Diagnostico standalone: prueba Whisper y el detector de expresion facial SIN necesitar
una sesion de WebRTC real. Corre esto directo en el servidor si las transcripciones o las
alertas de expresion no estan funcionando, para ver el error real (que normalmente queda
oculto en el log del servidor entre todo lo demas).

Uso:
    cd backend
    .venv\\Scripts\\python.exe diagnostico.py
"""
import sys

import numpy as np

print("=" * 70)
print("1) Cargando configuracion...")
print("=" * 70)
try:
    from app.core.config import settings

    print(f"  WHISPER_MODEL_SIZE = {settings.whisper_model_size}")
    print(f"  WHISPER_DEVICE = {settings.whisper_device}")
    print(f"  WHISPER_COMPUTE_TYPE = {settings.whisper_compute_type}")
    print(f"  YOLO_DEVICE = {settings.yolo_device}")
    print(f"  EMOCION_HABILITADA = {settings.emocion_habilitada}")
    print("  OK")
except Exception:
    print("  FALLO cargando configuracion:")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 70)
print("2) Probando carga de Whisper + transcripcion de un audio de prueba...")
print("=" * 70)
try:
    from app.services.stt.transcriber import Transcriptor

    transcriptor = Transcriptor()
    print("  Modelo Whisper cargado OK.")

    # 1 segundo de audio "hablado" sintetico (ruido con suficiente energia para pasar el
    # filtro de silencio; no producira texto real, solo prueba que el pipeline no truena).
    audio_prueba = (np.random.randn(16000).astype(np.float32) * 0.05)
    texto = transcriptor.transcribir_chunk(audio_prueba)
    print(f"  transcribir_chunk() corrio sin errores. Texto devuelto: {texto!r}")
    print("  OK (que salga vacio es normal, es ruido; lo importante es que no reviento)")
except Exception:
    print("  FALLO en Whisper -- ESTA es la causa de que no lleguen transcripciones:")
    import traceback

    traceback.print_exc()

print()
print("=" * 70)
print("3) Probando carga del detector de expresion facial (HSEmotion)...")
print("=" * 70)
try:
    from app.core.config import settings as settings2

    if not settings2.emocion_habilitada:
        print("  EMOCION_HABILITADA esta en False en la config -- por eso no llegan alertas")
        print("  de expresion. Ponlo en True (o quita EMOCION_HABILITADA=false del .env).")
    else:
        from app.services.emocion.detector import DetectorEmocion

        detector = DetectorEmocion()
        print("  Modelo HSEmotion cargado OK.")

        imagen_prueba = (np.random.rand(120, 120, 3) * 255).astype(np.uint8)
        etiqueta, probabilidad = detector.clasificar(imagen_prueba)
        print(f"  clasificar() corrio sin errores. Etiqueta: {etiqueta}, prob: {probabilidad:.2f}")
        print("  OK (la etiqueta en si no importa, es una imagen random; lo importante es que no reviento)")
except Exception:
    print("  FALLO en el detector de expresion -- ESTA es la causa de que no lleguen alertas de gestos:")
    import traceback

    traceback.print_exc()

print()
print("=" * 70)
print("4) Probando YOLO (deteccion de pose)...")
print("=" * 70)
try:
    from app.services.yolo.detector import DetectorYOLO

    detector_yolo = DetectorYOLO()
    frame_prueba = (np.random.rand(480, 640, 3) * 255).astype(np.uint8)
    resultado = detector_yolo.procesar_frame(frame_prueba)
    print(f"  procesar_frame() corrio sin errores. num_personas detectadas: {resultado['num_personas']}")
    print("  OK")
except Exception:
    print("  FALLO en YOLO:")
    import traceback

    traceback.print_exc()

print()
print("Diagnostico terminado.")
