# Cliente de escritorio (puesto del empleado)

Programa nativo que reemplaza el navegador: se abre solo, sin barra de direcciones ni
controles, apuntando directo al panel web del empleado que ya sirve el backend. El
empleado no tiene que "entrar a una app web" — el programa ya está mostrando su estación
cuando enciende el PC.

## Cómo funciona

- `app.py` abre una ventana embebida (WebView2 en Windows) cargando `servidor_url` de
  `config.json` — la misma página que hoy vive en
  [../frontend/employee/index.html](../frontend/employee/index.html), servida por FastAPI.
  No hay HTML duplicado: el programa es solo el "marco" nativo.
- Cerrar la ventana (la X) **no cierra el programa**, solo lo minimiza a la bandeja del
  sistema — así la transmisión de video/audio sigue activa aunque el empleado la oculte
  por error. Salir de verdad se hace desde el ícono de la bandeja → "Salir".
- **Identidad del puesto, atada al PC, no al navegador.** La primera vez que corre en un
  equipo, `app.py` genera un id único y lo guarda en `estacion_id.txt`, junto al propio
  programa (no en el cache del WebView, que se puede limpiar o perder). Ese id se manda
  como parámetro en la URL (`?estacion_id=...`) cada vez que abre la página del empleado,
  así que el supervisor siempre ve **la misma estación reconectando**, nunca una nueva —
  aunque se reinicie el programa, se borre caché, o cambie el nombre escrito.
- Opcionalmente, se puede fijar el nombre del empleado en `config.json`
  (`"empleado_nombre": "Laura Gómez"`) para que el puesto arranque identificado sin que
  nadie tenga que escribirlo — útil si cada PC es de un empleado fijo.

## Instalación en cada puesto de trabajo

1. Instalar Python 3.10+ en el PC del empleado (una sola vez).
2. Copiar la carpeta `desktop_client/` al equipo (o todo el repo, pero solo esta carpeta
   es necesaria en el cliente).
3. Editar [config.json](config.json): poner la IP real del servidor y, si se quiere fijar
   el puesto a un empleado específico, su nombre:
   ```json
   {
     "servidor_url": "http://<ip-del-servidor>:8000/empleado/",
     "empleado_nombre": "Laura Gómez",
     ...
   }
   ```
   (`empleado_nombre` puede dejarse vacío `""` si varios empleados rotan por el mismo PC —
   en ese caso lo escriben ellos cada vez, como hoy.)
4. Instalar dependencias y registrar el auto-arranque:
   ```bash
   cd desktop_client
   pip install -r requirements.txt
   python instalar_autoarranque.py
   ```
5. Reiniciar sesión de Windows (o ejecutar `pythonw app.py` una vez manualmente) para
   verificar que abre solo.

Para desinstalar el auto-arranque: `python instalar_autoarranque.py --quitar`.

> **Ojo al copiar `desktop_client/` a varios PCs:** si copias la carpeta después de haberla
> probado en un equipo, va a llevarse el `estacion_id.txt` de esa prueba — y todos los PCs
> terminarían compartiendo el mismo id de estación. Borra `estacion_id.txt` (si existe)
> antes de copiar la carpeta a cada equipo nuevo; se regenera solo en el primer arranque.

## Empaquetado como .exe (opcional, recomendado para despliegue masivo)

Para no depender de que cada PC tenga Python instalado, empaquetar con PyInstaller:

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --add-data "config.json;." --name ControlCalidadMonitor app.py
```

Esto genera `dist/ControlCalidadMonitor.exe`, que se puede copiar a cada equipo y apuntar
el `.bat` de auto-arranque a ese ejecutable en vez de a `pythonw app.py`.

## Notas importantes

- **Permisos de cámara/micrófono en WebView2:** la primera vez, Windows/Edge WebView2
  puede pedir permiso de cámara y micrófono para el proceso embebido. Hay que aceptarlo
  una vez por equipo (queda guardado).
- **Requiere red al servidor todo el tiempo.** Si el servidor se cae, el panel mostrará
  "Conexión perdida. Reintentando…" y reintentará solo cada 3 segundos (lógica ya
  incluida en [client.js](../frontend/employee/client.js)).
- Este cliente sigue siendo "ligero": toda la inferencia de YOLO/Whisper ocurre en el
  servidor, igual que con el navegador normal. Lo único que cambia es el empaquetado.
