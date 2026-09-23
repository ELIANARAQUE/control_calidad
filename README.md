# QA Monitor Local

Sistema de control de calidad en tiempo real: los puestos de empleados capturan
video/audio con el navegador (WebRTC) y lo envían a un servidor local con GPU,
donde YOLO (postura) y faster-whisper (voz) analizan los streams a baja tasa
de cuadros/chunks para no saturar la VRAM.

## Estructura

```
ControlCalidad/
├── backend/
│   ├── app/
│   │   ├── main.py                  # arranque FastAPI, monta rutas y estaticos
│   │   ├── api/
│   │   │   ├── signaling.py         # POST /api/offer -> negociacion WebRTC (aiortc)
│   │   │   └── supervisor.py        # WS /ws/supervisor -> alertas y transcripciones en vivo
│   │   ├── core/
│   │   │   ├── config.py            # settings (FPS, modelos, límites) vía .env
│   │   │   └── state.py             # registro de estaciones + bus de alertas en memoria
│   │   └── services/
│   │       ├── yolo/detector.py     # YOLO singleton + limitador de FPS + heurística de alerta
│   │       ├── stt/transcriber.py   # faster-whisper singleton
│   │       └── webrtc/tracks.py     # consumo de tracks WebRTC -> YOLO / Whisper
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── employee/                    # panel web del empleado (getUserMedia + WebRTC)
│   └── supervisor/                  # panel en vivo vía WebSocket
├── desktop_client/                  # programa nativo que envuelve frontend/employee (ver su README)
├── models/                          # pesos de YOLO (.pt) van aquí
└── recordings/                      # opcional, para evidencias grabadas
```

## Por qué estas decisiones de arquitectura

- **Un solo modelo YOLO y un solo Whisper cargados en memoria** (patrón singleton en
  [detector.py](backend/app/services/yolo/detector.py) y
  [transcriber.py](backend/app/services/stt/transcriber.py)), compartidos por todas las
  estaciones. Cargar un modelo por cámara agotaría la VRAM con 5-10 streams concurrentes.
- **Limitador de FPS por estación** ([`LimitadorFPS`](backend/app/services/yolo/detector.py)):
  WebRTC entrega video a 15-30 FPS, pero solo se procesan 2-5 FPS con YOLO; el resto de
  frames se descarta antes de llegar a la GPU.
- **Inferencia en `ThreadPoolExecutor`** ([tracks.py](backend/app/services/webrtc/tracks.py)):
  YOLO y Whisper son bloqueantes; correrlos directo en el event loop de asyncio congelaría
  la señalización WebRTC de todas las demás estaciones.
- **Estado de conexiones en memoria, sin base de datos** ([state.py](backend/app/core/state.py)):
  para 12-15 estaciones un `dict` con lock async es suficiente y evita infraestructura extra.
- **Modelo de pose liviano** (`yolov8n-pose.pt`) en vez de detección de objetos genérica:
  para "posturas, movimientos bruscos y gestos corporales" los keypoints de pose dan una
  señal más directa y barata que cajas delimitadoras + clasificación.
- **Movimiento brusco por pares de frames consecutivos dentro de una ventana**
  ([detector.py](backend/app/services/yolo/detector.py)): normaliza el desplazamiento por el
  ancho de hombros (no depende de la distancia a la cámara), ignora keypoints de baja
  confianza, y exige 2 pares consecutivos por encima del umbral para filtrar ruido de un
  solo frame — pero SÍ reacciona a un gesto breve aunque la persona vuelva enseguida a su
  posición de reposo (a diferencia de promediar toda la ventana, que lo "cancelaría").
- **Expresión facial (HSEmotion)** ([emocion/detector.py](backend/app/services/emocion/detector.py)):
  segundo modelo, liviano (~15MB, ONNX, corre en CPU sin competir por VRAM), entrenado sobre
  AffectNet (caras reales, no actuadas en laboratorio como el FER+ clásico) — es el estándar
  actual para reconocimiento de emoción facial liviano. Reutiliza los keypoints de nariz/ojos
  que YOLO-pose ya calcula para recortar la cara, sin detector de cara aparte. Alerta cuando
  "enojo/disgusto/desprecio" supera el umbral de probabilidad, con el mismo debounce + cooldown
  que la heurística de postura. El modelo se descarga solo a `~/.hsemotion/` la primera vez
  que arranca el servidor (requiere internet esa única vez).
- **Lenguaje inapropiado por palabras clave** ([lenguaje.py](backend/app/services/stt/lenguaje.py))
  sobre el texto ya transcrito por Whisper, con groserías/modismos colombianos — dejando fuera
  a propósito palabras ambiguas (ej. "chimba", "arrecho") que en Colombia se usan tanto en
  sentido positivo como ofensivo según el contexto.
- **Alertas guardadas en SQLite** ([db.py](backend/app/core/db.py)), con un `tipo`
  ('postura' / 'expresion' / 'lenguaje') y un veredicto pendiente que el supervisor marca
  como "real" o "falsa alarma" desde el panel. No es solo auditoría: es el dataset etiquetado
  que hace falta para, más adelante, entrenar modelos propios (temporal para postura/expresión,
  clasificador de toxicidad para lenguaje) y dejar de depender de heurísticas de umbral.

## Requisitos previos

- Python 3.10+ en el servidor con GPU NVIDIA (drivers CUDA instalados).
- `ffmpeg` instalado en el servidor (lo usa `av`/aiortc para decodificar).
- Descargar el modelo de pose y colocarlo en `models/` (no se versiona en git, ver `.gitignore`):
  ```bash
  # Ultralytics lo descarga solo si se deja solo el nombre, pero para control de
  # version explicito:
  python -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt')"
  # mover el .pt resultante a models/yolov8n-pose.pt
  ```
  El modelo de expresión facial (HSEmotion) no requiere este paso: se descarga solo a
  `~/.hsemotion/` la primera vez que arranca el servidor.

## Instalación

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # y ajustar según tu GPU/VRAM
```

> **Nota Windows/CUDA:** `pip install -r requirements.txt` instalará el `torch` de PyPI, que
> normalmente trae CUDA runtime empaquetado. Si `torch.cuda.is_available()` da `False`,
> reinstala torch siguiendo el selector oficial en https://pytorch.org/get-started/locally/
> (elige la versión CUDA que coincida con tu driver NVIDIA).

## Ejecución

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Empleados: en vez de abrir el navegador, ejecutan el [cliente de escritorio](desktop_client/README.md),
  que se instala una vez y arranca solo con Windows apuntando a `http://<ip-del-servidor>:8000/empleado/`.
  (Para pruebas rápidas o si prefieres el navegador, esa misma URL también funciona directo.)
- Supervisor abre: `http://<ip-del-servidor>:8000/supervisor/`

## Cambios recomendados antes de producción

1. **HTTPS/WSS obligatorio si sales de localhost.** `getUserMedia` exige contexto seguro:
   en LAN pura funciona por IP+HTTP en Chrome solo si se agrega la IP a
   `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, pero lo correcto es poner
   un proxy (Caddy/nginx) con certificado local (mkcert) delante del servidor.
2. **STUN/TURN si algún puesto no está en la misma LAN/VLAN** que el servidor — con
   `iceServers: []` (como está ahora) solo funciona si no hay NAT/firewall entre medio.
3. **Autenticación básica en `/api/offer` y `/ws/supervisor`** (por ejemplo, token compartido
   por estación) — ahora mismo cualquiera en la red podría conectar una "estación" falsa.
4. **Persistencia de alertas/transcripciones.** Hoy el `BusAlertas` solo transmite en vivo;
   si necesitas auditoría histórica, agrega SQLite (para este volumen no hace falta Postgres)
   y guarda cada evento antes de emitirlo.
5. **Métrica de VRAM real por lote.** Antes de escalar a 10 cámaras concurrentes, mide con
   `nvidia-smi` cuánta VRAM consume 1 stream a 3 FPS + Whisper `small`, y ajusta
   `YOLO_TARGET_FPS` / `WHISPER_MODEL_SIZE` según el resultado (ver siguiente sección).
6. **Cifrado/anonimización de datos biométricos.** Postura y voz de empleados son datos
   sensibles: define política de retención y aviso de privacidad antes de desplegar en
   producción (revisa requisitos legales locales de videovigilancia laboral).

## Dimensionamiento de GPU sugerido

| Componente | VRAM aprox. por stream | Notas |
|---|---|---|
| YOLOv8n-pose @ 480px, 3 FPS | ~0.3-0.5 GB | escala casi lineal con streams concurrentes |
| faster-whisper `small`, int8_float16 | ~0.5-1 GB (compartido, no por stream) | el modelo es compartido; el costo real es de cómputo, no de VRAM por estación |

Con una GPU de 8-12 GB deberías tener margen cómodo para 10 estaciones concurrentes a 3 FPS.
Si usas una GPU más modesta (ej. 4-6 GB), baja `YOLO_TARGET_FPS` a 2 y usa `whisper tiny/base`.

## Siguientes pasos naturales

- Añadir el heurístico de "tono de voz alterado" (energía/pitch) además de la transcripción.
- Panel de supervisor: agrupar eventos por estación en vez de un feed único.
- Grabar clips cortos (10-15s) alrededor de cada alerta para revisión posterior (ya existe
  la carpeta `recordings/` reservada para esto).
