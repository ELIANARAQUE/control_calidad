# Cliente de escritorio (puesto del empleado)

Programa nativo que reemplaza el navegador: se abre solo, sin barra de direcciones ni
controles, apuntando directo al panel web del empleado que ya sirve el backend. El
empleado no tiene que "entrar a una app web" — el programa ya está mostrando su estación
cuando enciende el PC. Instalarlo es, en la práctica, **copiar dos archivos y abrir uno
una vez**: todo lo demás (auto-arranque, identidad del puesto) se configura solo.

## Cómo funciona

- `app.py` abre una ventana embebida (WebView2 en Windows) cargando `servidor_url` de
  `config.json` — la misma página que hoy vive en
  [../frontend/employee/index.html](../frontend/employee/index.html), servida por FastAPI.
  No hay HTML duplicado: el programa es solo el "marco" nativo.
- Cerrar la ventana (la X) **no cierra el programa**, solo lo minimiza a la bandeja del
  sistema — así la transmisión de video/audio sigue activa aunque el empleado la oculte
  por error. Salir de verdad se hace desde el ícono de la bandeja → "Salir".
- **Auto-arranque que se configura solo.** La primera vez que `app.py` corre, se registra
  él mismo para abrir en el próximo inicio de sesión de Windows (ver
  [instalar_autoarranque.py](instalar_autoarranque.py)) — no hay que correr ningún script
  aparte a mano. Las siguientes veces no hace nada (no lo reescribe).
- **Identidad del puesto = identidad del PC, no del navegador ni de ningún archivo copiable.**
  Usa el `MachineGuid` que Windows ya genera por instalación (vive en el registro,
  `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography`), así que **aunque copies la misma
  carpeta o el mismo `.exe` a 15 PCs distintos, cada uno reporta con un id distinto
  automáticamente** — no depende de ningún archivo que haya que borrar o regenerar a mano.
  Ese id se manda como parámetro en la URL (`?estacion_id=...`) al panel del empleado, así
  que el supervisor siempre ve la misma estación reconectando, nunca una nueva.
- Opcionalmente, se puede fijar el nombre del empleado en `config.json`
  (`"empleado_nombre": "Laura Gómez"`) para que el puesto arranque identificado sin que
  nadie tenga que escribirlo — útil si cada PC es de un empleado fijo.

## Instalación en cada puesto de trabajo

### Opción A — como `.exe` (recomendada, no requiere Python en el PC del empleado)

1. En tu propia máquina (una sola vez), generar el ejecutable:
   ```bash
   cd desktop_client
   pip install -r requirements.txt
   build.bat
   ```
   Esto deja `dist/ControlCalidadMonitor.exe` y `dist/config.json` listos.
2. Editar `dist/config.json` con la IP real del servidor (y, opcional, el nombre del
   empleado si el PC es fijo):
   ```json
   { "servidor_url": "http://<ip-del-servidor>:8000/empleado/", "empleado_nombre": "" }
   ```
3. Copiar **ambos archivos** (`ControlCalidadMonitor.exe` + `config.json`, en la misma
   carpeta) al PC del empleado.
4. Abrir `ControlCalidadMonitor.exe` una vez. Listo — ya quedó configurado el
   auto-arranque y el id del puesto; no hace falta ningún otro paso ni ejecutar nada como
   administrador.

### Opción B — corriendo con Python (para desarrollo/pruebas)

1. Instalar Python 3.10+ en el equipo.
2. Copiar la carpeta `desktop_client/` completa.
3. Editar [config.json](config.json) con la IP del servidor.
4. ```bash
   cd desktop_client
   pip install -r requirements.txt
   python app.py
   ```
   El auto-arranque se configura solo en este primer arranque también.

Para desinstalar el auto-arranque en cualquiera de las dos opciones:
`python instalar_autoarranque.py --quitar` (o el `.bat` equivalente si no tienes Python,
ver `instalar_autoarranque.py` para el contenido exacto que borrar de la carpeta de Inicio
de Windows).

## Notas importantes

- **Permisos de cámara/micrófono en WebView2:** la primera vez, Windows/Edge WebView2
  puede pedir permiso de cámara y micrófono para el proceso embebido. Hay que aceptarlo
  una vez por equipo (queda guardado).
- **Requiere red al servidor todo el tiempo.** Si el servidor se cae, el panel mostrará
  "Conexión perdida. Reintentando…" y reintentará solo cada 3 segundos (lógica ya
  incluida en [client.js](../frontend/employee/client.js)).
- Este cliente sigue siendo "ligero": toda la inferencia de YOLO/Whisper ocurre en el
  servidor, igual que con el navegador normal. Lo único que cambia es el empaquetado.
- El `MachineGuid` de Windows es estable entre reinicios normales, pero algunas
  herramientas de "clonado" de imágenes de disco (Sysprep, por ejemplo) lo regeneran a
  propósito para evitar que dos PCs clonados compartan identidad — eso es lo correcto
  para este caso también.
