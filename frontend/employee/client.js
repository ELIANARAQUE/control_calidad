// Cliente de la estación de empleado: vista previa real de cámara/mic antes de iniciar,
// checkbox de Habeas Data obligatorio, luego WebRTC hacia el servidor + HUD de telemetría
// (ecualizador de audio real, cronómetro de turno, notificaciones del supervisor).

const punto = document.getElementById("punto");
const subtitulo = document.getElementById("subtitulo");
const config = document.getElementById("config");
const seccionActivo = document.getElementById("seccionActivo");
const nombreEmpleadoEl = document.getElementById("nombreEmpleado");
const btnCerrarSesionEmpleado = document.getElementById("btnCerrarSesionEmpleado");
const sedeSelect = document.getElementById("sedeSelect");
const moduloSelect = document.getElementById("moduloSelect");
const checkHabeasData = document.getElementById("checkHabeasData");
const btnIniciar = document.getElementById("btnIniciar");
const btnDetener = document.getElementById("btnDetener");
const video = document.getElementById("video");
const videoPreview = document.getElementById("videoPreview");
const previewPlaceholder = document.getElementById("previewPlaceholder");
const nombreActivo = document.getElementById("nombreActivo");
const idEstacion = document.getElementById("idEstacion");
const sedeModuloActivo = document.getElementById("sedeModuloActivo");
const sedeActiva = document.getElementById("sedeActiva");
const moduloActivo = document.getElementById("moduloActivo");
const sensibilidadActiva = document.getElementById("sensibilidadActiva");
const tiempoTurno = document.getElementById("tiempoTurno");
const barrasPreview = document.getElementById("barrasPreview");
const ecualizador = document.getElementById("ecualizador");
const bannerAviso = document.getElementById("banner-aviso");
const bannerAvisoTexto = document.getElementById("banner-aviso-texto");

const CLAVE_ESTACION = "qamonitor.estacionId";
// Guardadas por /login/ tras validar credenciales + rostro (ver frontend/login/index.html).
// Sin una de estas, esta pagina no deja hacer nada -se redirige a /login/ al cargar-.
const CLAVE_TOKEN = "qamonitor.token";
const CLAVE_SESION_NOMBRE = "qamonitor.nombre";
const CLAVE_SESION_ROL = "qamonitor.rol";
const CLAVE_HABEAS_DATA = "qamonitor.aceptoHabeasData";
const CLAVE_SEDE = "qamonitor.sede";
const CLAVE_MODULO = "qamonitor.modulo";
let pc = null;
let stream = null;
let streamPreview = null;
let audioCtx = null;
let analiser = null;
let inicioTurno = null;
let intervaloTurno = null;

function setEstado(texto, tipo = "neutro") {
  subtitulo.textContent = texto;
  subtitulo.classList.toggle("text-error", tipo === "error");
  punto.className = "punto w-2.5 h-2.5 rounded-full shrink-0" + (tipo === "conectado" ? " conectado" : tipo === "error" ? " error" : " bg-outline");
}

function mostrarPanelActivo(mostrar) {
  config.classList.toggle("oculto", mostrar);
  seccionActivo.classList.toggle("oculto", !mostrar);
}

function actualizarBotonIniciar() {
  btnIniciar.disabled = !(sessionStorage.getItem(CLAVE_TOKEN) && checkHabeasData.checked);
}
checkHabeasData.addEventListener("change", () => {
  // Se recuerda la aceptacion (igual que el nombre/sede) para que el programa de escritorio
  // pueda seguir iniciando la sesion en un solo paso en arranques posteriores, sin tener que
  // volver a marcar la casilla cada vez que se enciende el equipo.
  if (checkHabeasData.checked) localStorage.setItem(CLAVE_HABEAS_DATA, "1");
  else localStorage.removeItem(CLAVE_HABEAS_DATA);
  actualizarBotonIniciar();
});

// --- Opciones de sede/módulo: las administra el supervisor desde su panel; aqui solo se
// piden y se pintan. Las <option> que trae el HTML por defecto quedan como respaldo si esta
// llamada falla (servidor lento al arrancar, etc.) para no dejar los select vacios. ---
async function cargarOpcionesSedeModulo() {
  try {
    const resp = await fetch("/api/config/opciones");
    if (!resp.ok) return;
    const datos = await resp.json();
    if (Array.isArray(datos.sede) && datos.sede.length) {
      const valorPrevio = sedeSelect.value;
      sedeSelect.innerHTML = datos.sede.map((v) => `<option value="${v}">${v}</option>`).join("");
      if (datos.sede.includes(valorPrevio)) sedeSelect.value = valorPrevio;
    }
    if (Array.isArray(datos.modulo) && datos.modulo.length) {
      const valorPrevio = moduloSelect.value;
      moduloSelect.innerHTML = datos.modulo.map((v) => `<option value="${v}">${v}</option>`).join("");
      if (datos.modulo.includes(valorPrevio)) moduloSelect.value = valorPrevio;
    }
    // Reaplica lo guardado en localStorage (si sigue existiendo en la lista actualizada)
    const sedeGuardada = localStorage.getItem(CLAVE_SEDE);
    const moduloGuardado = localStorage.getItem(CLAVE_MODULO);
    if (sedeGuardada && datos.sede?.includes(sedeGuardada)) sedeSelect.value = sedeGuardada;
    if (moduloGuardado && datos.modulo?.includes(moduloGuardado)) moduloSelect.value = moduloGuardado;
  } catch (err) {
    // se quedan las opciones por defecto del HTML
  }
}

// --- Vista previa de cámara/mic antes de iniciar sesión (chequeo real de hardware) ---
async function iniciarPreview() {
  try {
    streamPreview = await navigator.mediaDevices.getUserMedia({
      video: { width: 320, height: 240 },
      audio: true,
    });
    videoPreview.srcObject = streamPreview;
    previewPlaceholder.classList.add("oculto");
    animarBarras(streamPreview, [...barrasPreview.children]);

    // DEBUG temporal: confirma en la consola del navegador (F12) si el permiso de
    // microfono realmente entrego una pista de audio utilizable, antes de siquiera
    // intentar conectarse al servidor.
    const pistasAudio = streamPreview.getAudioTracks();
    console.log("[debug-audio-navegador] pistas de audio obtenidas:", pistasAudio.length, pistasAudio);
    if (pistasAudio.length === 0) {
      previewPlaceholder.textContent = "Cámara OK, pero NO se detectó micrófono";
      previewPlaceholder.classList.remove("oculto");
    } else {
      console.log("[debug-audio-navegador] microfono:", pistasAudio[0].label, "estado:", pistasAudio[0].readyState, "muted:", pistasAudio[0].muted);
    }
  } catch (err) {
    previewPlaceholder.textContent = "No se pudo acceder a cámara/micrófono";
    console.log("[debug-audio-navegador] getUserMedia fallo:", err);
  }
}

function animarBarras(streamAudio, barras) {
  if (!streamAudio.getAudioTracks().length) return;
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  const fuente = audioCtx.createMediaStreamSource(streamAudio);
  const analizadorLocal = audioCtx.createAnalyser();
  analizadorLocal.fftSize = 64;
  fuente.connect(analizadorLocal);
  const datos = new Uint8Array(analizadorLocal.frequencyBinCount);

  function loop() {
    if (!barras[0].isConnected) return; // el DOM cambio (seccion oculta), se detiene solo
    analizadorLocal.getByteFrequencyData(datos);
    const promedio = datos.reduce((a, b) => a + b, 0) / datos.length;
    barras.forEach((barra, i) => {
      const variacion = datos[i % datos.length] || 0;
      const altura = Math.min(100, Math.max(12, ((promedio + variacion) / 2 / 255) * 100));
      barra.style.height = altura + "%";
    });
    requestAnimationFrame(loop);
  }
  loop();
}

// --- Sesión activa ---
async function iniciarMonitoreo() {
  const token = sessionStorage.getItem(CLAVE_TOKEN);
  const nombreEmpleado = sessionStorage.getItem(CLAVE_SESION_NOMBRE);
  if (!token || !nombreEmpleado) {
    window.location.href = "/login/";
    return;
  }

  btnIniciar.disabled = true;
  setEstado("Solicitando cámara y micrófono…");

  try {
    stream = streamPreview || (await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, frameRate: 15 },
      audio: { echoCancellation: true, noiseSuppression: true },
    }));
  } catch (err) {
    setEstado("No se pudo acceder a cámara/micrófono: " + err.message, "error");
    btnIniciar.disabled = false;
    return;
  }

  video.srcObject = stream;
  animarBarras(stream, [...ecualizador.children]);

  // DEBUG temporal: confirma que el stream que se va a mandar por WebRTC de verdad trae
  // audio (si esto sale con audio:0, el problema es del navegador/mic de este equipo, no
  // del servidor).
  console.log("[debug-audio-navegador] pistas en el stream a transmitir:", {
    video: stream.getVideoTracks().length,
    audio: stream.getAudioTracks().length,
  });

  // El STUN es necesario en cuanto esta estacion deja de estar en la misma red local que el
  // servidor (ej. accediendo desde afuera por el tunel): sin el, el navegador solo ofrece su
  // IP privada como candidato, inalcanzable desde fuera de esta LAN.
  pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  stream.getTracks().forEach((track) => pc.addTrack(track, stream));

  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "connected") {
      setEstado("Sesión activa · transmitiendo en vivo", "conectado");
    } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
      setEstado("Conexión perdida. Reintentando…", "error");
      setTimeout(() => iniciarMonitoreo(), 3000);
    }
  };

  setEstado("Negociando conexión con el servidor…");

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await esperarIceCompleto(pc);

  let respuesta;
  try {
    respuesta = await fetch("/api/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
        token,
        sede: sedeSelect.value,
        modulo: moduloSelect.value,
        acepto_habeas_data: checkHabeasData.checked,
        estacion_id: localStorage.getItem(CLAVE_ESTACION) || undefined,
      }),
    });
  } catch (err) {
    setEstado("No se pudo contactar al servidor: " + err.message, "error");
    btnIniciar.disabled = false;
    return;
  }

  if (respuesta.status === 401) {
    cerrarSesionEmpleado();
    return;
  }
  if (!respuesta.ok) {
    const detalle = await respuesta.json().catch(() => ({}));
    // FastAPI devuelve `detail` como texto en errores propios, pero como una LISTA de objetos
    // en errores de validacion (422): sin convertirlo, la pantalla mostraba "[object Object]".
    const mensaje = Array.isArray(detalle.detail)
      ? detalle.detail.map((d) => `${(d.loc || []).slice(-1)[0] || "dato"}: ${d.msg}`).join("; ")
      : detalle.detail;
    setEstado(mensaje || "El servidor rechazó la conexión (código " + respuesta.status + ")", "error");
    btnIniciar.disabled = false;
    return;
  }

  const datos = await respuesta.json();
  await pc.setRemoteDescription({ sdp: datos.sdp, type: datos.type });
  localStorage.setItem(CLAVE_ESTACION, datos.estacion_id);

  nombreActivo.textContent = nombreEmpleado;
  idEstacion.textContent = datos.estacion_id;
  sedeModuloActivo.textContent = [sedeSelect.value, moduloSelect.value].filter(Boolean).join(" · ");
  sedeActiva.textContent = sedeSelect.value || "—";
  moduloActivo.textContent = moduloSelect.value || "—";
  mostrarPanelActivo(true);
  setEstado("Sesión activa · transmitiendo en vivo", "conectado");

  inicioTurno = Date.now();
  clearInterval(intervaloTurno);
  intervaloTurno = setInterval(actualizarCronometro, 1000);
  actualizarCronometro();

  cargarSensibilidadActiva();
  conectarNotificaciones();
}

function actualizarCronometro() {
  const segundos = Math.floor((Date.now() - inicioTurno) / 1000);
  const hh = String(Math.floor(segundos / 3600)).padStart(2, "0");
  const mm = String(Math.floor((segundos % 3600) / 60)).padStart(2, "0");
  const ss = String(segundos % 60).padStart(2, "0");
  tiempoTurno.textContent = `${hh}:${mm}:${ss}`;
}

async function cargarSensibilidadActiva() {
  try {
    const resp = await fetch("/api/config/sensibilidad");
    const datos = await resp.json();
    sensibilidadActiva.textContent = datos.nivel;
  } catch (err) {
    sensibilidadActiva.textContent = "—";
  }
}

function detenerMonitoreo() {
  if (pc) {
    pc.close();
    pc = null;
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  clearInterval(intervaloTurno);
  mostrarPanelActivo(false);
  btnIniciar.disabled = false;
  setEstado("Sesión finalizada. Ingresa tu nombre para reiniciar.");
  iniciarPreview();
}

function esperarIceCompleto(peerConnection) {
  return new Promise((resolve) => {
    if (peerConnection.iceGatheringState === "complete") {
      resolve();
      return;
    }
    function verificar() {
      if (peerConnection.iceGatheringState === "complete") {
        peerConnection.removeEventListener("icegatheringstatechange", verificar);
        resolve();
      }
    }
    peerConnection.addEventListener("icegatheringstatechange", verificar);
  });
}

// --- Notificaciones del supervisor (avisos generales) ---
function conectarNotificaciones() {
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocolo}://${location.host}/api/ws/notificaciones`);
  ws.onmessage = (msg) => {
    const datos = JSON.parse(msg.data);
    bannerAvisoTexto.textContent = datos.mensaje;
    bannerAviso.classList.remove("oculto");
    clearTimeout(conectarNotificaciones._t);
    conectarNotificaciones._t = setTimeout(() => bannerAviso.classList.add("oculto"), 8000);
  };
}

function cerrarSesionEmpleado() {
  sessionStorage.removeItem(CLAVE_TOKEN);
  sessionStorage.removeItem(CLAVE_SESION_NOMBRE);
  sessionStorage.removeItem(CLAVE_SESION_ROL);
  window.location.href = "/login/";
}
btnCerrarSesionEmpleado.addEventListener("click", (ev) => {
  ev.preventDefault();
  cerrarSesionEmpleado();
});

btnIniciar.addEventListener("click", () => {
  if (!checkHabeasData.checked) return;
  iniciarMonitoreo();
});

btnDetener.addEventListener("click", detenerMonitoreo);

// El programa de escritorio (ver desktop_client/app.py) abre esta pagina con
// ?estacion_id=... como parametro de URL: viene de un archivo que el propio programa guarda
// junto a si mismo en el PC (estable entre reinicios, no depende del cache del navegador
// embebido). El nombre del empleado YA NO se toma de la URL ni de un campo de texto libre:
// ahora viene de la cuenta autenticada en /login/ (con verificacion facial), guardada en
// sessionStorage -sin una sesion valida ahi, esta pagina redirige a /login/-.
window.addEventListener("DOMContentLoaded", async () => {
  const token = sessionStorage.getItem(CLAVE_TOKEN);
  const nombreSesion = sessionStorage.getItem(CLAVE_SESION_NOMBRE);
  if (!token || !nombreSesion) {
    window.location.href = "/login/";
    return;
  }
  nombreEmpleadoEl.textContent = nombreSesion;

  iniciarPreview();
  await cargarOpcionesSedeModulo();

  const parametros = new URLSearchParams(window.location.search);
  const estacionIdDelPrograma = parametros.get("estacion_id");
  if (estacionIdDelPrograma) {
    localStorage.setItem(CLAVE_ESTACION, estacionIdDelPrograma);
  }

  const sedeGuardada = localStorage.getItem(CLAVE_SEDE);
  const moduloGuardado = localStorage.getItem(CLAVE_MODULO);
  if (sedeGuardada) sedeSelect.value = sedeGuardada;
  if (moduloGuardado) moduloSelect.value = moduloGuardado;
  sedeSelect.addEventListener("change", () => localStorage.setItem(CLAVE_SEDE, sedeSelect.value));
  moduloSelect.addEventListener("change", () => localStorage.setItem(CLAVE_MODULO, moduloSelect.value));

  const yaAceptoHabeasData = localStorage.getItem(CLAVE_HABEAS_DATA) === "1";
  checkHabeasData.checked = yaAceptoHabeasData;
  actualizarBotonIniciar();

  if (yaAceptoHabeasData) {
    // Arranque en un solo paso (equipo del programa de escritorio, consentimiento ya dado
    // en una sesion anterior en este mismo equipo).
    iniciarMonitoreo();
  } else {
    setEstado("Acepta el aviso de datos para iniciar la sesión de monitoreo");
  }
});
