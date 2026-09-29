# Dockerfile — Control de Calidad (backend FastAPI + frontend estatico), modo CPU para Railway.
#
# Railway no ofrece GPU: esta imagen instala PyTorch CPU-only (en vez del build CUDA que usa
# requirements.txt para desarrollo local con GPU) y arranca con WHISPER_DEVICE=cpu /
# YOLO_DEVICE=cpu (ver DEPLOY_RAILWAY.md para las variables de entorno completas).
#
# WORKDIR final: /app/backend -porque app/main.py monta el frontend con rutas relativas
# ("../frontend/...") y app/core/config.py apunta al modelo YOLO con "../models/..."-, con
# /app/frontend y /app/models como hermanos de /app/backend, igual que en desarrollo local
# donde se corre `uvicorn` parado dentro de `backend/`.
#
# Build en dos etapas: la primera (builder) tiene los compiladores y headers que faster-whisper/
# deepface/mediapipe/opencv a veces necesitan para compilar dependencias transitivas sin wheel
# para Python 3.12 en slim; la imagen final NO los arrastra, solo el venv ya armado.

# ---------------------------------------------------------------------------
# Etapa 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Compiladores y headers para paquetes que no traen wheel manylinux para todas las plataformas
# (p. ej. alguna dependencia transitiva de mediapipe/onnxruntime/tensorflow en arquitecturas
# menos comunes). No queda en la imagen final.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

COPY backend/requirements.txt .

# 1) PyTorch: requirements.txt fija torch/torchvision para el build CUDA de desarrollo local
#    (ver el comentario en ese archivo, `--index-url .../cu128`). Para Railway (sin GPU) se
#    instala la variante CPU-only, con el MISMO pin de version, desde el indice CPU oficial de
#    PyTorch. Se instala ANTES y aparte para que el paso 2 no reinstale la variante CUDA al
#    resolver requirements.txt tal cual viene.
# 2) nvidia-cublas-cu12 / nvidia-cudnn-cu12: solo sirven para acelerar faster-whisper (CTranslate2)
#    en GPU vía CUDA; en CPU no se usan y son paquetes grandes (varios cientos de MB), así que se
#    excluyen del install para no inflar la imagen.
# El resto de requirements.txt se instala tal cual (opencv-python-headless, ultralytics,
# faster-whisper, deepface, tensorflow, etc. no dependen de la variante de torch).
RUN grep -v -E '^(torch==|torchvision==|nvidia-cublas-cu12|nvidia-cudnn-cu12)' requirements.txt > requirements-cpu.txt \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-cpu.txt

# ---------------------------------------------------------------------------
# Etapa 2: imagen final
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Librerias de sistema en runtime (no de build):
#   - libgl1 / libglib2.0-0: opencv-python-headless, mediapipe y deepface las importan en
#     tiempo de ejecucion aunque sea headless (libGL.so.1 / libgthread-2.0.so.0), si faltan
#     el import falla con "ImportError: libGL.so.1: cannot open shared object file".
#   - libsm6 / libxext6 / libxrender1: dependencias de X11 que opencv/mediapipe tocan al cargar
#     aunque no haya display real (headless server, sin GUI).
#   - libgomp1: OpenMP, usado por onnxruntime/torch/ultralytics para paralelizar en CPU.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# frontend/ y models/ como hermanos de backend/ (ver nota de WORKDIR arriba). models/ puede
# llegar vacio: el modelo yolov8n-pose.pt no esta committeado (.gitignore lo excluye) y
# Ultralytics lo descarga solo la primera vez que arranca, si no lo encuentra en la ruta
# configurada (ver DEPLOY_RAILWAY.md).
COPY frontend/ /app/frontend/
COPY models/ /app/models/
COPY backend/ /app/backend/

WORKDIR /app/backend

# Railway inyecta PORT dinamicamente; no se puede hardcodear en un CMD exec-form (no expande
# variables), asi que se usa shell-form para que $PORT se resuelva al arrancar el contenedor.
# 8000 como default para correr la imagen fuera de Railway (docker run sin -e PORT=...).
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
