## Estado de infraestructura (piloto de 1 estación — migración a Postgres nativo)

Proyecto Railway: **Control-Calidad** (`b9e518dd-5410-4ff4-b91a-dd90cd2eaadd`, workspace
ValledelSoftware), environment **production** (`9555e278-d7b2-40e3-abc7-84312bccd248`).

Servicios creados hasta ahora:

| Servicio | ID | Estado |
|---|---|---|
| **Postgres** (template oficial `postgres`, imagen `ghcr.io/railwayapp-templates/postgres-ssl:18`) | `448de72f-fdf1-45b7-b3f1-23dba18cd88c` | Desplegado y corriendo. Volumen propio `postgres-volume` (`1885543e-da13-4506-a7a3-86a008937f25`) montado en `/var/lib/postgresql/data`, gestionado por el template. |
| **control-calidad-backend** | `96872e11-0c8a-433b-b26f-f7a7b1f2d340` | Creado, **SIN código conectado todavía** (a propósito: la migración de `olaf` no terminó). Tiene ya `DATABASE_URL` referenciado al plugin de Postgres (`${{ Postgres.DATABASE_URL }}`) y un Volume propio `control-calidad-backend-volume` (`8e833aff-168c-44ef-bce0-6d6d2c26dd8c`) montado en `/app/backend/data` (ver justificación de la ruta abajo). |

### Ruta del Volume: `/app/backend/data`

Confirmado revisando el código (no asumido):
- `RUTA_CAPTURAS` (`backend/app/core/db.py:32`) = `Path(__file__).parent.parent.parent / "data" / "capturas"`,
  es decir `backend/data/capturas` relativo al repo. Ahí escriben `app/services/webrtc/tracks.py`
  (capturas de alertas) y se lee desde `app/api/alertas.py`, `app/services/informes/historial.py`
  y `app/services/informes/reporte.py`.
- El `Dockerfile` deja el WORKDIR final en `/app/backend` (`frontend/`, `models/` y `backend/` son
  hermanos bajo `/app/`), así que en el contenedor esa ruta es `/app/backend/data` — ahí se montó
  el Volume, cubre tanto `data/capturas/` como cualquier otra cosa que se agregue bajo `data/`
  (p. ej. si la migración de fotos de rostro de `cuentas.py` termina moviéndolas de Supabase
  Storage a disco, lo natural es que caigan bajo `data/` también y queden cubiertas por el mismo
  Volume sin cambios de infraestructura).

### `DATABASE_URL` — ya resuelta por referencia, no hace falta copiarla a mano

`add_reference_variable` dejó `DATABASE_URL=${{ Postgres.DATABASE_URL }}` en el servicio
`control-calidad-backend`: Railway resuelve el valor real del plugin de Postgres automáticamente
y se actualiza sola si el plugin rota la contraseña. El nombre exacto que usa el template y que
espera el código (`app/core/db_client.py` vía `settings.database_url`) es **`DATABASE_URL`** (no
`DATABASE_PUBLIC_URL` ni `POSTGRES_URL` — esas no existen en este template; las variables que sí
expone son `DATABASE_URL`, `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` y
`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`, todas apuntando a la red privada
`postgres.railway.internal`, solo alcanzable entre servicios del mismo proyecto).

### ✅ RESUELTO — `backend/postgres_schema.sql` ya se aplicó contra el Postgres real

El schema **ya se aplicó con éxito** contra la base real de Railway (10 tablas confirmadas, 154
términos del diccionario de lenguaje cargados). El Postgres de Railway ya no está vacío.
Actualización del punto anterior de este documento (quedó resuelto por fuera de este archivo, no
hizo falta exponer el puerto 5432 con un TCP Proxy).

### Variables de entorno pendientes de setear en `control-calidad-backend`

Ya seteada: `DATABASE_URL` (referencia automática, ver arriba). Faltan estas (mismas del `.env`
local, ver `backend/app/core/config.py`) — no las puedo setear yo porque son secretos que no
tengo:

| Variable | Nota |
|---|---|
| `DATABASE_URL` | Ya seteada automáticamente por referencia al plugin de Postgres (`${{ Postgres.DATABASE_URL }}`), no hace falta setearla a mano ni copiarla — Railway la resuelve sola (ver sección de arriba). Es la única variable de base de datos: ya no hace falta `SUPABASE_URL`/`SUPABASE_KEY` (Supabase se reemplazó por completo por este Postgres nativo; las fotos de empleados también se movieron a disco cifrado, ver `app/core/cuentas.py`). |
| `FERNET_KEY` | Obligatoria. Misma clave que en local si querés poder descifrar los datos ya cifrados (documento/correo/fotos), o generar una nueva con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` si el piloto arranca con datos nuevos. |
| `WHISPER_MODEL_SIZE` | Sugerido `deepdml/faster-whisper-large-v3-turbo-ct2` (o achicar a `small`/`base` si la latencia en CPU resulta inaceptable). |
| `WHISPER_DEVICE` | `cpu` (distinto del default `cuda` del código). |
| `WHISPER_COMPUTE_TYPE` | `int8` (distinto del default `int8_float16`, que es de GPU). |
| `YOLO_DEVICE` | `cpu` (distinto del default `cuda:0`). |
| `WEBRTC_STUN` | `stun:stun.l.google.com:19302` como mínimo; ver sección "WebRTC" más abajo sobre TURN si alguna estación queda detrás de NAT restrictivo. |

### Conectar el repo cuando el código esté listo

Cuando `olaf` confirme que la migración de código está lista en `main`, conectar el servicio
existente (no crear uno nuevo) con `connect_service_source` apuntando a
`ELIANARAQUE/control_calidad`, rama `main` — eso sí va a disparar un build/deploy real (Railway
no permite conectar un source de GitHub sin que arranque el primer build), así que esa acción se
coordina con vos antes de ejecutarla.

---

# Despliegue en Railway (modo CPU)

Railway no ofrece GPU. Esta app corre ahí con Whisper, YOLO y DeepFace sobre **CPU** — el
análisis en vivo (transcripción, pose, emociones) va a ser más lento que en un equipo local con
GPU NVIDIA, algo ya aceptado para este despliegue. Este documento cubre solo lo necesario para
que la app **arranque y funcione** en CPU en Railway, no optimización de rendimiento.

## Build

Railway detecta el `Dockerfile` en la raíz del repo automáticamente (hay además un
`railway.json` que lo deja explícito: `"builder": "DOCKERFILE"`). No hace falta configurar
build command ni start command a mano: el `CMD` del Dockerfile ya arranca uvicorn escuchando en
`0.0.0.0:$PORT` (Railway inyecta `PORT` dinámicamente en cada deploy).

## Variables de entorno a cargar en Railway

Configuralas en el servicio (Settings → Variables), son las mismas del `.env` local salvo las
marcadas como distintas para CPU/Railway:

| Variable | Valor sugerido | Nota |
|---|---|---|
| `DATABASE_URL` | (referencia automática al plugin de Postgres) | obligatoria, sin esto el backend no arranca — Railway ya la resuelve sola vía `${{ Postgres.DATABASE_URL }}`, no hace falta setearla a mano (ver sección de arriba). Es la única variable de base de datos: ya no existe `SUPABASE_URL`/`SUPABASE_KEY`, Supabase se reemplazó por completo por este Postgres nativo. |
| `FERNET_KEY` | la misma clave que uses en local (o una nueva generada con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) | si cambia, los datos ya cifrados (documento, correo, fotos en disco) quedan ilegibles |
| `WHISPER_MODEL_SIZE` | `deepdml/faster-whisper-large-v3-turbo-ct2` (o achicalo, ver nota abajo) | modelo grande en CPU es mucho más lento que en GPU |
| `WHISPER_DEVICE` | `cpu` | **distinto de local** (`cuda` en desarrollo con GPU) |
| `WHISPER_COMPUTE_TYPE` | `int8` | **distinto de local** (`int8_float16` es la cuantización de GPU; `int8` es la de CPU — es la misma que ya usa el fallback automático a CPU en `transcriber.py`) |
| `YOLO_DEVICE` | `cpu` | **distinto de local** (`cuda:0` en desarrollo con GPU). El código ya detecta `torch.cuda.is_available()` y cae solo a CPU si no hay GPU, pero fijarlo explícito deja el log claro y evita ambigüedad |
| `WEBRTC_STUN` | `stun:stun.l.google.com:19302` (o tu propio STUN/TURN) | **casi seguro hace falta en Railway** (ver sección abajo), a diferencia de LAN local donde se deja vacío |

Variables opcionales (tienen default razonable en `config.py`, cargalas solo si querés otro
valor): `WHISPER_MODELO_CPU` (default `small`, usado en el fallback automático si `cuda` falla
en runtime), `EMOCION_*`, `AUSENCIA_UMBRAL_SEGUNDOS`, `SESION_INACTIVIDAD_SEGUNDOS`, etc.

**Nunca** subas el archivo `.env` al repo ni a la imagen (`.dockerignore` ya lo excluye
explícitamente).

### Nota sobre el tamaño del modelo Whisper en CPU

`large-v3-turbo` (~1.6 GB) fue elegido pensando en GPU. En CPU va a ser notablemente más lento
por chunk de audio. Si la latencia de transcripción resulta inaceptable en producción, considerá
bajar `WHISPER_MODEL_SIZE` a un modelo más chico (p. ej. `small` o `base`, ya usados como
fallback de CPU en el propio código) — es un cambio de una sola variable de entorno, no de
código.

## WebRTC: STUN/TURN casi seguro hace falta

En LAN local, `WEBRTC_STUN` se deja vacío a propósito (todas las estaciones y el servidor están
en la misma red, no hace falta negociar NAT). En Railway el servidor **no** está en la red local
de las estaciones — cada estación se conecta desde su propia red, típicamente detrás de NAT — así
que casi siempre hace falta:

1. Un servidor **STUN** como mínimo (`stun:stun.l.google.com:19302` es público y gratis, sirve
   para NAT simétrico simple).
2. Si alguna estación está detrás de una red institucional con NAT restrictivo o firewall que
   bloquea UDP saliente (frecuente en redes corporativas/educativas), STUN solo no alcanza y va a
   hacer falta un servidor **TURN** (relay), que sí tiene costo de banda ancha porque el tráfico de
   video/audio pasa por él. Opciones: correr tu propio `coturn`, o un servicio administrado (p. ej.
   Twilio STUN/TURN, Cloudflare Calls, Metered.ca).

Si después del deploy alguna estación no logra conectar la cámara/audio (se queda colgada en el
modal de carga o reintenta las 3 veces y falla), es la primera causa a revisar: probablemente esa
red necesita TURN y no solo STUN.

## Modelo de YOLO (`models/yolov8n-pose.pt`)

El archivo `.pt` **no está en el repo** (`.gitignore` excluye `models/*.pt`). El Dockerfile copia
la carpeta `models/` tal cual esté en el build context (puede llegar vacía) — Ultralytics
descarga el peso automáticamente la primera vez que arranca si no lo encuentra en
`yolo_model_path` (`../models/yolov8n-pose.pt` relativo a `backend/`, o sea `/app/models/` dentro
del contenedor), igual que ya pasa en desarrollo local en la primera corrida.

Esto tiene una implicación en Railway: el filesystem del contenedor es efímero entre deploys, así
que **cada deploy nuevo vuelve a descargar el modelo** al arrancar (agrega unos segundos al
primer arranque, el archivo pesa pocos MB). Si eso resulta molesto, se puede:
- Committear el `.pt` directamente en `models/` (quitando la línea correspondiente del
  `.gitignore`), para que quede horneado en la imagen sin depender de la descarga en runtime, o
- Agregar un volumen de Railway montado en `/app/models` para que persista entre deploys.

Ninguno de los dos es obligatorio para que la app funcione: sin volumen y sin committear el
`.pt`, igual arranca y funciona (solo repite la descarga en cada deploy).

## Verificar el despliegue

Con el CLI de Railway ya logueado y el servicio linkeado:

```bash
railway deployment list --limit 1 --json
```

Confirmá `status == "SUCCESS"`. Si queda en `BUILDING`/`DEPLOYING` esperá y reintentá; si queda
en `FAILED`/`CRASHED`, revisá con:

```bash
railway logs --build
railway logs
```

Errores típicos a esa altura:
- `ImportError: libGL.so.1: cannot open shared object file` → falta una lib de sistema en la
  imagen final (el Dockerfile ya instala `libgl1`/`libglib2.0-0`/`libsm6`/`libxext6`/
  `libxrender1`/`libgomp1`; si aparece otra lib faltante, agregala en la segunda etapa del
  Dockerfile).
- `cublas64_12.dll is not found` o similar de CUDA → revisá que `WHISPER_DEVICE=cpu` esté
  seteado; sin esto, Whisper intenta `cuda` primero y solo cae a CPU tras el primer chunk fallido
  (el sistema se auto-recupera solo, pero agrega un log de warning y un chunk perdido al arrancar).
- Falla instalando dependencias de Python en el build → revisar si alguna versión pineada en
  `backend/requirements.txt` dejó de tener wheel disponible para Python 3.12 en `linux/amd64`
  (Railway construye para esa plataforma); puede hacer falta agregar alguna lib de build
  adicional a la etapa `builder` del Dockerfile.
