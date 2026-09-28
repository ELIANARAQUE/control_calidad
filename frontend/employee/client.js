// Cliente de la estación de empleado: vista previa real de cámara/mic antes de iniciar,
// checkbox de Habeas Data obligatorio, luego WebRTC hacia el servidor + HUD de telemetría
// (ecualizador de audio real, cronómetro de turno, notificaciones del supervisor).

const punto = document.getElementById("punto");
const subtitulo = document.getElementById("subtitulo");
const config = document.getElementById("config");
const seccionActivo = document.getElementById("seccionActivo");
const nombreEmpleadoEl = document.getElementById("nombreEmpleado");
const btnCerrarSesionLateral = document.getElementById("btnCerrarSesionLateral");
let promesaPreview = Promise.resolve(); // se resuelve cuando la vista previa de camara termina de arrancar
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

// --- Modales de carga y de error al iniciar el monitoreo ---
const modalCargando = document.getElementById("modalCargandoMonitoreo");
const pasoCargando = document.getElementById("pasoCargandoMonitoreo");
const modalError = document.getElementById("modalErrorMonitoreo");

function mostrarCarga(paso) {
  pasoCargando.textContent = paso;
  modalCargando.classList.remove("oculto");
}
function ocultarCarga() {
  modalCargando.classList.add("oculto");
}
function mostrarError({ mensaje, sugerencia = "", codigo = "" }) {
  ocultarCarga();
  document.getElementById("textoErrorMonitoreo").textContent = mensaje;
  document.getElementById("sugerenciaErrorMonitoreo").textContent = sugerencia;
  document.getElementById("codigoErrorMonitoreo").textContent = codigo ? `Código técnico: ${codigo}` : "";
  modalError.classList.remove("oculto");
  btnIniciar.disabled = !checkHabeasData.checked;
}
document.getElementById("btnCerrarErrorMonitoreo").addEventListener("click", () => modalError.classList.add("oculto"));
document.getElementById("btnReintentarMonitoreo").addEventListener("click", () => {
  modalError.classList.add("oculto");
  iniciarMonitoreo();
});

// Traduce el error del navegador al pedir la camara a un mensaje entendible.
function errorDeCamara(err) {
  const casos = {
    NotAllowedError: [
      "No diste permiso para usar la cámara y el micrófono.",
      "Haz clic en el candado de la barra de direcciones, permite cámara y micrófono y vuelve a intentarlo.",
    ],
    NotReadableError: [
      "La cámara o el micrófono están siendo usados por otra aplicación.",
      "Cierra Teams, Zoom u otra pestaña que use la cámara, y vuelve a intentarlo.",
    ],
    NotFoundError: [
      "No se encontró una cámara o un micrófono en este equipo.",
      "Conecta una cámara web y un micrófono y vuelve a intentarlo.",
    ],
    OverconstrainedError: ["La cámara no soporta la configuración pedida.", "Prueba con otra cámara."],
  };
  const [mensaje, sugerencia] = casos[err.name] || [
    "No se pudo acceder a la cámara o el micrófono.",
    "Revisa que estén conectados y con permiso en el navegador.",
  ];
  return { mensaje, sugerencia, codigo: `${err.name}: ${err.message}` };
}

// Traduce una respuesta de error del servidor a { mensaje, sugerencia, codigo }.
async function errorDeServidor(respuesta) {
  const cuerpo = await respuesta.json().catch(() => ({}));
  const detalle = Array.isArray(cuerpo.detail)
    ? cuerpo.detail.map((d) => `${(d.loc || []).slice(-1)[0] || "dato"}: ${d.msg}`).join("; ")
    : cuerpo.detail;
  const sugerencias = {
    400: "Marca la casilla de aceptación del aviso de tratamiento de datos y vuelve a intentarlo.",
    422: "La página del navegador está desactualizada: recárgala con Ctrl + F5.",
    503: "Se alcanzó el máximo de estaciones conectadas a la vez: espera a que otra se desconecte.",
  };
  return {
    mensaje: detalle || "El servidor rechazó la conexión.",
    sugerencia:
      sugerencias[respuesta.status] ||
      (respuesta.status >= 500 ? "Error interno del servidor: avisa al administrador." : ""),
    codigo: `HTTP ${respuesta.status} en /api/offer`,
  };
}

function conTiempoLimite(promesa, ms, mensaje) {
  return Promise.race([promesa, new Promise((_, rechazar) => setTimeout(() => rechazar(new Error(mensaje)), ms))]);
}

function esperarConexion(peer, ms) {
  return new Promise((resolver, rechazar) => {
    if (peer.connectionState === "connected") return resolver();
    const temporizador = setTimeout(() => rechazar(new Error("tiempo agotado")), ms);
    peer.addEventListener("connectionstatechange", () => {
      if (peer.connectionState === "connected") {
        clearTimeout(temporizador);
        resolver();
      } else if (peer.connectionState === "failed") {
        clearTimeout(temporizador);
        rechazar(new Error("conexión fallida"));
      }
    });
  });
}

// --- Sesión activa ---
let iniciando = false;
let cierreIntencional = false; // true cuando el propio empleado detiene: NO se reconecta solo
let reintentosReconexion = 0;
const MAX_REINTENTOS_RECONEXION = 3;

async function obtenerStream() {
  // Reusa la vista previa si sigue viva: pedir la camara dos veces a la vez falla en Windows
  // con "la camara esta en uso", que era una de las causas del error intermitente.
  await promesaPreview;
  const vivo = streamPreview && streamPreview.getTracks().every((t) => t.readyState === "live");
  if (vivo) return streamPreview;
  return navigator.mediaDevices.getUserMedia({
    video: { width: 640, height: 480, frameRate: 15 },
    audio: { echoCancellation: true, noiseSuppression: true },
  });
}

async function iniciarMonitoreo({ esReconexion = false } = {}) {
  if (iniciando) return;
  const token = sessionStorage.getItem(CLAVE_TOKEN);
  const nombreEmpleado = sessionStorage.getItem(CLAVE_SESION_NOMBRE);
  if (!token || !nombreEmpleado) {
    window.location.href = "/login/";
    return;
  }
  if (!checkHabeasData.checked) {
    mostrarError({
      mensaje: "Debes aceptar el aviso de tratamiento de datos personales para iniciar el monitoreo.",
      sugerencia: "Marca la casilla de aceptación y vuelve a intentarlo.",
    });
    return;
  }

  iniciando = true;
  btnIniciar.disabled = true;
  modalError.classList.add("oculto");
  if (pc) {
    cierreIntencional = true; // cerrar la conexion vieja no debe disparar otra reconexion
    pc.close();
    pc = null;
  }
  cierreIntencional = false;

  try {
    mostrarCarga(esReconexion ? "Reconectando con el servidor…" : "Preparando cámara y micrófono…");
    try {
      stream = await obtenerStream();
    } catch (err) {
      mostrarError(errorDeCamara(err));
      return;
    }
    video.srcObject = stream;
    animarBarras(stream, [...ecualizador.children]);

    // El STUN es necesario en cuanto esta estacion deja de estar en la misma red local que el
    // servidor: sin el, el navegador solo ofrece su IP privada como candidato.
    const peer = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
    pc = peer;
    stream.getTracks().forEach((track) => peer.addTrack(track, stream));

    mostrarCarga("Preparando la conexión de video…");
    await peer.setLocalDescription(await peer.createOffer());
    await conTiempoLimite(esperarIceCompleto(peer), 10000, "ice").catch(() => {}); // sigue con lo que haya

    mostrarCarga("Conectando con el servidor de monitoreo…");
    let respuesta;
    try {
      respuesta = await conTiempoLimite(
        fetch("/api/offer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sdp: peer.localDescription.sdp,
            type: peer.localDescription.type,
            token,
            sede: sedeSelect.value,
            modulo: moduloSelect.value,
            acepto_habeas_data: checkHabeasData.checked,
            estacion_id: localStorage.getItem(CLAVE_ESTACION) || undefined,
          }),
        }),
        20000,
        "El servidor no respondió en 20 segundos."
      );
    } catch (err) {
      mostrarError({
        mensaje: "No se pudo contactar al servidor de monitoreo.",
        sugerencia: "Revisa tu conexión a la red y que el servidor esté encendido.",
        codigo: err.message,
      });
      return;
    }
    if (respuesta.status === 401) {
      cerrarSesionEmpleado();
      return;
    }
    if (!respuesta.ok) {
      mostrarError(await errorDeServidor(respuesta));
      return;
    }

    const datos = await respuesta.json();
    await peer.setRemoteDescription({ sdp: datos.sdp, type: datos.type });
    localStorage.setItem(CLAVE_ESTACION, datos.estacion_id);

    mostrarCarga("Estableciendo la transmisión de video y audio…");
    try {
      await esperarConexion(peer, 20000);
    } catch (err) {
      mostrarError({
        mensaje: "El servidor respondió, pero no se pudo establecer la transmisión de video y audio.",
        sugerencia: "Suele ser un firewall o la red bloqueando la conexión. Reintenta; si persiste, avisa al administrador.",
        codigo: `WebRTC: ${err.message} (estado ${peer.connectionState})`,
      });
      return;
    }

    peer.addEventListener("connectionstatechange", () => manejarCambioConexion(peer));
    reintentosReconexion = 0;
    ocultarCarga();

    nombreActivo.textContent = nombreEmpleado;
    idEstacion.textContent = datos.estacion_id;
    sedeModuloActivo.textContent = [sedeSelect.value, moduloSelect.value].filter(Boolean).join(" · ");
    sedeActiva.textContent = sedeSelect.value || "—";
    moduloActivo.textContent = moduloSelect.value || "—";
    mostrarPanelActivo(true);
    setEstado("Sesión activa · transmitiendo en vivo", "conectado");

    if (!esReconexion) {
      inicioTurno = Date.now();
      clearInterval(intervaloTurno);
      intervaloTurno = setInterval(actualizarCronometro, 1000);
      actualizarCronometro();
      cargarSensibilidadActiva();
      conectarNotificaciones();
    }
  } catch (err) {
    mostrarError({ mensaje: "Ocurrió un error inesperado al iniciar el monitoreo.", codigo: String(err) });
  } finally {
    iniciando = false;
  }
}

// Si la conexion se cae SIN que el empleado haya detenido la sesion, se reintenta unas pocas
// veces con el modal de carga visible; despues se muestra el error, en vez de reintentar para
// siempre en silencio (antes, detener la sesion tambien disparaba una reconexion sola).
function manejarCambioConexion(peer) {
  if (peer !== pc || cierreIntencional) return;
  if (!["failed", "disconnected", "closed"].includes(peer.connectionState)) return;
  if (reintentosReconexion >= MAX_REINTENTOS_RECONEXION) {
    mostrarPanelActivo(false);
    mostrarError({
      mensaje: "Se perdió la conexión con el servidor de monitoreo.",
      sugerencia: "Revisa tu red y vuelve a iniciar el monitoreo.",
      codigo: `WebRTC: estado ${peer.connectionState} tras ${reintentosReconexion} reintentos`,
    });
    return;
  }
  reintentosReconexion += 1;
  mostrarCarga(`Se perdió la conexión. Reconectando (intento ${reintentosReconexion} de ${MAX_REINTENTOS_RECONEXION})…`);
  setTimeout(() => iniciarMonitoreo({ esReconexion: true }), 2000);
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
  cierreIntencional = true;
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
  setEstado("Sesión de monitoreo finalizada.");
  promesaPreview = iniciarPreview();
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

async function cerrarSesionEmpleado() {
  if (pc) detenerMonitoreo();
  try {
    // Invalida el token en el servidor y borra la cookie de sesion: sin esto, /empleado/
    // seguiria abriendo aunque aqui se borre lo guardado en el navegador.
    await fetch("/api/auth/logout", { method: "POST", headers: { "X-Auth-Token": sessionStorage.getItem(CLAVE_TOKEN) || "" } });
  } catch (err) {
    // sin conexion: igual se limpia lo local y se manda al login
  }
  sessionStorage.removeItem(CLAVE_TOKEN);
  sessionStorage.removeItem(CLAVE_SESION_NOMBRE);
  sessionStorage.removeItem(CLAVE_SESION_ROL);
  window.location.href = "/login/";
}
for (const boton of [btnCerrarSesionLateral, document.getElementById("btnCerrarSesionHeader")]) {
  boton.addEventListener("click", (ev) => {
    ev.preventDefault();
    cerrarSesionEmpleado();
  });
}

// --- Panel izquierdo: "Iniciar monitoreo" / "Ver histórico" ---
function mostrarVista(vista) {
  document.getElementById("vistaMonitoreo").classList.toggle("oculto", vista !== "monitoreo");
  document.getElementById("vistaHistorico").classList.toggle("oculto", vista !== "historico");
  document.querySelectorAll(".nav-empleado[data-vista]").forEach((b) => b.classList.toggle("activa", b.dataset.vista === vista));
  if (vista === "historico") cargarHistorico();
}
document.querySelectorAll(".nav-empleado[data-vista]").forEach((b) =>
  b.addEventListener("click", () => mostrarVista(b.dataset.vista))
);

function horaLegible(iso) {
  return new Date(iso).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
}
function duracionLegible(inicioIso, finIso) {
  const minutos = Math.max(0, Math.round((new Date(finIso) - new Date(inicioIso)) / 60000));
  return minutos < 60 ? `${minutos} min` : `${Math.floor(minutos / 60)} h ${minutos % 60} min`;
}

// Solo el historial de conexiones propio: sin fotos, alertas ni reportes (eso es del supervisor).
async function cargarHistorico() {
  const tabla = document.getElementById("tablaHistorico");
  const vacio = document.getElementById("vacioHistorico");
  tabla.innerHTML = '<tr><td colspan="6" class="py-space-md text-center text-on-surface-variant">Cargando…</td></tr>';
  try {
    const resp = await fetch("/api/mis-sesiones", { headers: { "X-Auth-Token": sessionStorage.getItem(CLAVE_TOKEN) || "" } });
    if (resp.status === 401) return cerrarSesionEmpleado();
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const sesiones = await resp.json();
    vacio.classList.toggle("oculto", sesiones.length > 0);
    tabla.innerHTML = sesiones
      .map(
        (s) => `<tr class="border-b border-outline-variant">
          <td class="py-space-sm pr-space-sm">${new Date(s.inicio).toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" })}</td>
          <td class="py-space-sm pr-space-sm">${horaLegible(s.inicio)}</td>
          <td class="py-space-sm pr-space-sm">${s.fin ? horaLegible(s.fin) : '<span class="chip-en-curso">En curso</span>'}</td>
          <td class="py-space-sm pr-space-sm">${duracionLegible(s.inicio, s.fin || new Date().toISOString())}</td>
          <td class="py-space-sm pr-space-sm">${s.sede || "—"}</td>
          <td class="py-space-sm">${s.modulo || "—"}</td>
        </tr>`
      )
      .join("");
  } catch (err) {
    tabla.innerHTML = `<tr><td colspan="6" class="py-space-md text-center text-error">No se pudo cargar el histórico (${err.message}).</td></tr>`;
  }
}

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
  const partes = nombreSesion.trim().split(/\s+/);
  document.getElementById("avatarEmpleado").textContent = (partes[0][0] + (partes[1]?.[0] || "")).toUpperCase();

  promesaPreview = iniciarPreview();
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
