# Control de Calidad — Universitaria de Colombia

## ¿Qué es y para qué sirve?

**Control de Calidad** es un sistema de monitoreo en tiempo real de la **calidad de la atención** que prestan los empleados en las ventanillas y módulos de servicio de la Universitaria de Colombia.

Mientras el empleado atiende, el sistema analiza la cámara y el micrófono de su estación. Así detecta automáticamente situaciones que afectan la atención al estudiante:

- **Lenguaje inapropiado:** groserías (con un diccionario de modismos colombianos) y frases de **mal trato** o de negación de ayuda, por ejemplo "no lo puedo ayudar" o "averigüe en otro lado".
- **Expresiones faciales:** gestos negativos (enojo, disgusto, desprecio) y también expresiones positivas (felicidad).
- **Ausencia del puesto:** si no hay nadie frente a la cámara durante varios minutos.
- **Transcripción de voz:** todo lo que dice el empleado queda escrito, para poder revisar si respondió a lo que el usuario solicitaba.

El **supervisor (administrador)** ve todo esto en vivo en su panel, califica cada alerta como "Fue real" o "Falsa alarma", envía comunicados a las estaciones y descarga el **historial completo en Excel o PDF** (sesiones, alertas, transcripciones, almuerzos y breaks), filtrado por fechas, empleado, sede o módulo.

El empleado puede **pausar su sesión para salir a almuerzo o a un break**: mientras tanto no se transmite ni se analiza nada, y el tiempo de cada pausa queda registrado.

El acceso es con **cuenta propia y verificación facial**, y el tratamiento de los datos cumple con la **Ley 1581 de 2012 (Habeas Data)**: el empleado debe aceptar el aviso antes de cada sesión de monitoreo.

---

## Funcionalidades

### Cuentas y acceso
- **Registro de usuarios** con validaciones:
  - Nombre: solo letras, máximo 32.
  - Documento: solo números, máximo 15.
  - Correo: sin espacios y terminado en `@universitariadecolombia.edu.co` (cualquier otro dominio da error).
  - Contraseña: sin espacios, máximo 16, con botón para mostrarla.
- **Tres fotos de rostro obligatorias** en el registro: frontal, lateral izquierda y lateral derecha. Solo se toman con la cámara en vivo; no se aceptan fotos subidas desde el computador.
- **Guía de cámara con óvalo:** solo deja tomar la foto cuando el rostro está dentro del óvalo, al tamaño correcto y en el ángulo pedido. Rechaza la foto si hay más de una persona.
- **Un rostro, una cuenta:** no se puede registrar dos veces a la misma persona.
- **Dos roles, empleado y administrador.** Crear un administrador exige la **clave de super admin**, que está guardada en la base de datos.
- **Login en dos pasos:**
  1. Correo y contraseña.
  2. Verificación facial en vivo, comparada contra las fotos del registro.

  Según el rol, lleva a la estación del empleado o al panel del supervisor.
- **Sesión validada por el servidor:** sin iniciar sesión no se abre ninguna página, y cada rol solo entra a la suya. La sesión usa una cookie HttpOnly.
- **Varias pestañas:** con una sesión abierta, al abrir el login en otra pestaña se va directo a la vista del usuario, sin volver a pedir inicio de sesión.
- **Cierre automático de sesión:** cada página abierta avisa al servidor cada 25 segundos. Si se cierra el navegador (aunque sea por accidente), la sesión se cierra sola a los 2 minutos y hay que volver a iniciar sesión.

### Estación del empleado
- **Panel lateral** con "Iniciar monitoreo", "Ver histórico" y "Cerrar sesión".
- **Vista previa de cámara y micrófono**, con medidor de nivel de audio en tiempo real (también durante la transmisión).
- **Datos de la sesión:** se elige sede o modalidad y módulo o ventanilla (listas administradas por el supervisor) y se acepta el aviso de Habeas Data.
- **El monitoreo solo arranca al presionar el botón.**
- **Inicio rápido del monitoreo** (menos de un segundo en la red local), con un **modal de carga** que muestra el paso (1 a 4), una barra de progreso y los segundos transcurridos. Si algo falla, un **modal de error** con la causa real, una sugerencia y el código técnico. Si la conexión se cae, reintenta hasta 3 veces.
- **Salir a almuerzo / Tomar un break:** con la transmisión activa, el empleado puede pausar la sesión. La cámara y el micrófono dejan de transmitirse y de analizarse, se muestra un cronómetro (en almuerzo, cuánto le queda de la hora) y el botón "Volver al trabajo" la reanuda. Cada pausa queda guardada en la base de datos.
- **Histórico de conexiones propio:** fecha, inicio, fin, duración, sede, módulo y el tiempo total de almuerzo y de break de cada sesión (sin fotos ni reportes).
- **Comunicados del supervisor:** cuando el administrador envía un "Aviso a Estaciones", a todos los empleados con su vista abierta (estén o no monitoreando) les aparece un modal con el mensaje, que solo se cierra con "Cerrar comunicado".

### Panel del supervisor (administrador)
- **Centro de Monitoreo:**
  - Indicadores generales.
  - Lista de los empleados conectados (nombre, sede, módulo y alertas pendientes). Al hacer clic en uno se ve **su cámara en vivo**, a unos 10 cuadros por segundo.
  - Si el empleado está en almuerzo o break, en lugar del video aparece "Sesión pausada · tiempo de almuerzo / break" con los minutos que lleva.
  - Emoción actual de cada empleado.
  - Filtros de cámaras: conectadas, desconectadas y con alertas.
- **Centro de control por estación:** una sola persona con su video, alertas, emociones y transcripciones de la sesión actual.
- **Transcripciones:** todo lo que se habló, con buscador.
- **Detección de Lenguaje:** groserías y mal trato, cada una con su calificación (Fue real / Falsa alarma).
- **Gestos y Expresiones:**
  - Pestaña **negativas:** se califican.
  - Pestaña **positivas:** solo se pueden eliminar.
- **Alerta crítica:** una expresión muy negativa abre un **modal que pide gestión inmediata**, en cualquier página del panel.
- **Campana de notificaciones** con las alertas de lenguaje pendientes.
- **Aviso a estaciones:** mensaje en vivo a todos los empleados con su vista abierta; les aparece como un modal que deben cerrar.
- **Historial y Reportes:**
  - **Historial completo**: una fila por cada sesión de monitoreo de todos los empleados, con hora de inicio, hora de fin, duración y sus alertas (con detalle desplegable).
  - **Filtros por rango de fechas, empleado, sede y módulo** (combinables).
  - **Almuerzos y breaks por sesión:** tiempo TOTAL de cada tipo (sumando todas las veces que salió), cuántas veces y el tiempo efectivo de la sesión (sin pausas). El detalle muestra cada salida y regreso.
  - **Exportar a Excel o PDF** todo lo filtrado, o solo las filas marcadas. El Excel viene desglosado en hojas: Resumen (totales y resumen por empleado), Sesiones, Pausas (cada almuerzo y break), Alertas (con la foto de cada una) y Transcripciones.
  - **Reporte Excel individual** por trabajador (respeta el periodo filtrado), con hojas de Resumen, Detalle (con fotos), Transcripciones y Emociones.
- **Sedes y Módulos:** CRUD de las opciones que el empleado elige al iniciar su monitoreo (añadir, editar, eliminar). Los registros anteriores no se modifican.
- **Recuperación de contraseña:** el administrador escribe el correo del empleado, el sistema verifica que la cuenta exista y le asigna una contraseña nueva (con confirmación). Solo aplica a cuentas de empleado.

### Análisis automático (servidor)
- **Voz a texto:** Whisper `large-v3-turbo` en GPU, en español, con filtros contra frases inventadas por el modelo.
- **Lenguaje inapropiado:** diccionario en la base de datos con **154 términos** en tres categorías:
  - Groserías fuertes.
  - Groserías leves.
  - Frases de mal trato.

  Detecta frases de varias palabras y letras estiradas ("gonorreaaa"), y no se confunde con palabras que contienen el término ("computadora").
- **Expresiones faciales:** modelo HSEmotion entrenado con caras naturales (AffectNet). Promedia varios cuadros y suma las emociones negativas, así no hace falta exagerar el gesto.
- **Detección de persona y ausencia:** YOLOv8-pose.
- **Fotos automáticas** en el momento de cada alerta.

### Seguridad y protección de datos
- **Contraseñas** (y la clave de super admin) guardadas con **bcrypt**, un método irreversible.
- **Datos personales cifrados** con `cryptography` (Fernet): número de documento y correo.
- **Fotos de rostro cifradas**, tanto las del registro como las de las alertas. Solo se descifran para un administrador con sesión iniciada o al generar su reporte.
- **Aceptación de Habeas Data** registrada en cada sesión.

---

## Tecnologías

| Parte | Tecnología |
|---|---|
| Servidor | Python 3.12, FastAPI, Uvicorn |
| Video y audio en vivo | WebRTC (aiortc en el servidor, navegador en la estación) |
| Base de datos y archivos | Supabase (Postgres + Storage) |
| Voz a texto | faster-whisper (`large-v3-turbo`) con GPU CUDA |
| Pose y presencia | Ultralytics YOLOv8-pose |
| Emociones | HSEmotion (`enet_b2_8`, ONNX) |
| Reconocimiento facial | DeepFace (Facenet + RetinaFace) y MediaPipe Face Landmarker (guía del óvalo) |
| Frontend | HTML, JavaScript y Tailwind CSS |
| Reportes | openpyxl (Excel del historial y reporte individual), jsPDF (PDF del historial) |

---

## Estructura del proyecto

```
ControlCalidad/
├── backend/
│   ├── app/
│   │   ├── main.py                    # arranque de FastAPI, rutas, páginas y control de sesión
│   │   ├── api/
│   │   │   ├── auth.py                # registro, login, verificación facial, cierre de sesión
│   │   │   ├── signaling.py           # inicio de la transmisión WebRTC (/api/offer)
│   │   │   ├── supervisor.py          # WebSocket en vivo del panel del supervisor
│   │   │   ├── alertas.py             # veredictos, fotos de alertas, eliminar expresiones positivas
│   │   │   └── estaciones.py          # estaciones, pausas, sedes/módulos, reportes, historial
│   │   ├── core/
│   │   │   ├── config.py              # configuración (se ajusta desde .env)
│   │   │   ├── supabase_client.py     # conexión a Supabase (una por hilo, con reintentos)
│   │   │   ├── db.py                  # consultas a la base de datos
│   │   │   ├── cuentas.py             # usuarios, fotos de rostro, super admin
│   │   │   ├── seguridad.py           # bcrypt y cifrado Fernet
│   │   │   ├── auth.py                # tokens de sesión y roles
│   │   │   └── state.py               # estaciones conectadas y eventos en vivo
│   │   └── services/
│   │       ├── webrtc/tracks.py       # procesa video y audio de cada estación
│   │       ├── stt/transcriber.py     # Whisper (voz a texto)
│   │       ├── stt/lenguaje.py        # detección de groserías y mal trato
│   │       ├── emocion/detector.py    # expresiones faciales
│   │       ├── yolo/detector.py       # detección de persona
│   │       ├── rostros/reconocimiento.py  # verificación facial del login
│   │       ├── informes/historial.py  # Excel del historial (Resumen, Sesiones, Pausas, Alertas, Transcripciones)
│   │       └── informes/reporte.py    # reporte Excel individual por trabajador
│   ├── supabase_version_definitiva.sql  # script completo de la base de datos
│   └── requirements.txt
├── frontend/
│   ├── login/                         # inicio de sesión con verificación facial
│   ├── registro/                      # registro de cuentas (3 fotos, roles)
│   ├── employee/                      # estación del empleado
│   ├── supervisor/                    # panel del supervisor (8 páginas, incluidas Recuperación y Sedes y Módulos)
│   └── comun/                         # guía de cámara con óvalo y su modelo
├── desktop_client/                    # programa de escritorio opcional (ver su README)
└── models/                            # pesos de YOLO (.pt)
```

---

## Instalación

### 1. Requisitos
- **Windows** con Python **3.12**.
- **GPU NVIDIA** (recomendada; probado con RTX 5060 Ti) con el driver actualizado.
- Un proyecto en **[Supabase](https://supabase.com)**.

### 2. Entorno virtual y dependencias
Desde la carpeta `backend`:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Instala primero PyTorch con soporte CUDA. El `cu128` es necesario para GPUs RTX 50xx:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

Y luego el resto:

```bash
pip install -r requirements.txt
```

### 3. Base de datos
En Supabase, ve a **SQL Editor → New query**, pega todo el contenido de `backend/supabase_version_definitiva.sql` y dale **Run**.

El script crea todas las tablas y carga los datos iniciales:
- tipos de documento,
- clave de super admin,
- opciones de sede y módulo,
- diccionario de lenguaje,
- tabla `pausas` (cada almuerzo y break) y la vista `pausas_por_sesion`, que da el tiempo total de cada tipo de pausa por sesión.

| Tabla | Qué guarda |
|---|---|
| `usuarios` | Cuentas (datos personales cifrados, contraseña con bcrypt, rostro) |
| `tipos_documento`, `super_admin` | Catálogo de documentos y clave de super admin |
| `eventos_conexion` | Cada conexión y desconexión de una estación (inicio y fin de sesión) |
| `alertas` | Lenguaje, expresiones, ausencia (con veredicto y foto cifrada) |
| `transcripciones`, `emociones` | Lo que se habló y la emoción detectada |
| `pausas` | Almuerzos y breaks (salida y regreso) |
| `opciones_configurables` | Sedes y módulos |
| `lenguaje_inapropiado` | Diccionario de groserías y mal trato |

Se puede correr sobre una base existente sin perder datos: no borra nada y solo crea lo que falte. **Cada vez que el sistema se actualice con tablas nuevas, vuelve a correrlo completo.**

#### Mantenimiento de la base de datos
Cambiar la clave de super admin (reemplaza `NuevaClave`):

```sql
update super_admin set clave_hash = crypt('NuevaClave', gen_salt('bf')), actualizado_en = now() where id = 1;
```

Vaciar los registros de monitoreo (**borra todo el historial de forma permanente**; usuarios, sedes y diccionario se conservan):

```sql
truncate table eventos_conexion, alertas, transcripciones, emociones, pausas restart identity;
```

### 4. Archivo `.env`
Crea `backend/.env` con:

```
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu-secret-key-de-supabase
FERNET_KEY=clave-de-cifrado
WHISPER_MODEL_SIZE=deepdml/faster-whisper-large-v3-turbo-ct2
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=int8_float16
YOLO_DEVICE=cuda:0
# Opcional: solo si las estaciones NO están en la misma red local que el servidor
# WEBRTC_STUN=stun:stun.l.google.com:19302
```

- `SUPABASE_KEY` es la **secret key** del proyecto (antes llamada *service role key*), no la *publishable key*.
- Para crear la `FERNET_KEY`, ejecuta:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  **Guarda una copia segura de esa clave:** si se pierde, los datos cifrados ya no se pueden leer.
- `WEBRTC_STUN` se deja vacío en la red local: así el monitoreo arranca en menos de un segundo. Con un STUN que la red bloquea, cada inicio tardaba unos 15 segundos.
- El `.env` **no se sube a GitHub**.

### 5. Arrancar el servidor
Desde `backend`, con el entorno virtual:

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

La primera vez descarga los modelos de IA (Whisper pesa unos 1,6 GB), así que tarda unos minutos. Está listo cuando aparece `Application startup complete`.

---

## Uso

| Página | Dirección |
|---|---|
| Iniciar sesión | `http://localhost:8000/login/` |
| Registro de cuentas | `http://localhost:8000/registro/` |
| Estación del empleado | `http://localhost:8000/empleado/` (después del login) |
| Panel del supervisor | `http://localhost:8000/supervisor/` (después del login) |

**Clave de super admin inicial:** `SAdmin123`. Se pide al registrar una cuenta de administrador y se cambia con el script de *Mantenimiento de la base de datos* (arriba).

### Usarlo desde otros equipos de la red
1. Averigua la IP del servidor con `ipconfig` (por ejemplo `192.168.40.28`).
2. Permite conexiones entrantes a Python en el Firewall de Windows.
3. En los otros equipos, entra a `http://IP-DEL-SERVIDOR:8000/login/`.
4. Como no es HTTPS, el navegador bloquea la cámara. En Edge, ve a `edge://flags/#unsafely-treat-insecure-origin-as-secure`, agrega `http://IP-DEL-SERVIDOR:8000`, ponlo en **Enabled** y reinicia el navegador.

---

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `No module named 'supabase'` o `'app'` | No se activó el entorno virtual o no se está en `backend`. Usa `.venv\Scripts\python.exe -m uvicorn ...` desde `backend`. |
| Una función nueva da `404` | El servidor sigue con el código anterior: reinícialo (Ctrl + C y arrancar de nuevo). |
| La página se ve desactualizada | Presiona **Ctrl + F5** en el navegador. |
| Las listas de sede o módulo salen vacías | Agrega opciones en *Sedes y Módulos*. |
| `httpx.RemoteProtocolError: Server disconnected` | Supabase cerró una conexión inactiva. El servidor ya reintenta solo con una conexión nueva; si sigue pasando, revisa la conexión a internet. |
| "Falta la tabla 'pausas'" al salir a almuerzo o break | La base de datos no está actualizada: vuelve a correr `supabase_version_definitiva.sql` completo. |
| El monitoreo tarda mucho en iniciar | Revisa que `WEBRTC_STUN` esté vacío en `.env` si todo está en la misma red local. |
| `cublas64_12.dll is not found` | Instala PyTorch con CUDA (paso 2). Si la GPU falla, Whisper pasa solo a CPU. |
| Avisos de TensorFlow o DeepFace al arrancar | Son informativos, no errores. |
