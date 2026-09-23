# Cliente de escritorio (puesto del empleado)

Programa nativo que reemplaza el navegador: se abre solo, sin barra de direcciones ni
controles, apuntando directo al panel web del empleado que ya sirve el backend. El
empleado no tiene que "entrar a una app web" — el programa ya está mostrando su estación
cuando enciende el PC.

Se distribuye como **un solo archivo `.exe`**: se lleva en USB o se descarga, se abre una
vez, y queda completamente instalado. Sin config que editar en el PC del empleado, sin
pasos como administrador, sin script aparte que correr.

## Cómo funciona

- `app.py` abre una ventana embebida (WebView2 en Windows) cargando la página del
  empleado que ya sirve el backend
  ([../frontend/employee/index.html](../frontend/employee/index.html)) — no hay HTML
  duplicado, el programa es solo el "marco" nativo.
- Cerrar la ventana (la X) **no cierra el programa**, solo lo minimiza a la bandeja del
  sistema — así la transmisión de video/audio sigue activa aunque el empleado la oculte
  por error. Salir de verdad se hace desde el ícono de la bandeja → "Salir".
- **Se instala solo al primer arranque.** Si detecta que se está ejecutando desde una
  ubicación temporal (la USB, la carpeta de Descargas), se copia solo a una carpeta
  permanente del perfil de Windows y se relanza desde ahí — así, aunque saques la USB
  después, el programa (y su auto-arranque) siguen funcionando.
- **Auto-arranque que se configura solo**, en ese mismo primer arranque: se registra para
  abrir en el próximo inicio de sesión de Windows (ver
  [instalar_autoarranque.py](instalar_autoarranque.py)). Las siguientes veces no hace
  nada (no lo reescribe).
- **Identidad del puesto = identidad del PC**, no de ningún archivo copiable. Usa el
  `MachineGuid` que Windows ya genera por instalación (vive en el registro,
  `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography`), así que **aunque lleves el mismo
  `.exe` a 15 PCs distintos, cada uno reporta con un id distinto automáticamente** — no
  depende de ningún archivo que haya que borrar o regenerar a mano.
- La IP del servidor queda **incrustada dentro del `.exe`** al construirlo (ver abajo) —
  no hay `config.json` externo que llevar ni editar por PC.

## Cómo generar el `.exe` (una sola vez, en tu máquina)

1. Editar [config.json](config.json) con la IP real del servidor:
   ```json
   { "servidor_url": "http://<ip-del-servidor>:8000/empleado/", "empleado_nombre": "" }
   ```
   (`empleado_nombre` puede dejarse fijo si el PC es de un empleado específico — el
   programa arranca ya identificado sin que nadie escriba nada. Si varios empleados
   rotan por el mismo equipo, se deja vacío `""` y lo escriben ellos.)
2. ```bash
   cd desktop_client
   pip install -r requirements.txt
   build.bat
   ```
3. Listo: `dist/ControlCalidadMonitor.exe` es el único archivo que hace falta llevar a
   cada puesto de trabajo.

> Si el servidor cambia de IP más adelante, hay que repetir estos pasos y volver a
> distribuir el `.exe` — la IP queda fija dentro del ejecutable, a propósito, para que no
> haga falta ningún archivo de configuración aparte en los PCs de los empleados.

## Instalación en cada puesto de trabajo

Copiar `ControlCalidadMonitor.exe` (por USB, red compartida, o descarga) y abrirlo una
vez. Eso es todo — no requiere Python instalado, no requiere permisos de administrador,
no requiere ningún otro archivo.

Para desinstalar el auto-arranque, borrar `ControlCalidadMonitor.bat` de la carpeta de
Inicio de Windows (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) — o, si
tienes Python disponible, `python instalar_autoarranque.py --quitar`.

## Desarrollo/pruebas (con Python, sin empaquetar)

```bash
cd desktop_client
pip install -r requirements.txt
python app.py
```

En este modo el programa lee `config.json` de esta misma carpeta (no incrustado) y no
hace la auto-instalación a una carpeta permanente — solo aplica al `.exe` empaquetado.

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
- Antivirus/SmartScreen pueden advertir la primera vez que se abre un `.exe` sin firmar
  descargado o traído de fuera — es normal para ejecutables sin certificado de firma de
  código; firmar el binario es un paso aparte si se quiere evitar ese aviso.
