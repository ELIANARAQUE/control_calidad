// Cliente ligero: captura camara/microfono y establece una conexion WebRTC con el servidor.
// No hace ningun procesamiento de IA en el navegador (el PC del empleado es de baja potencia).
// Pensado para correr tanto en un navegador normal como embebido dentro del programa de escritorio.

const punto = document.getElementById("punto");
const subtitulo = document.getElementById("subtitulo");
const config = document.getElementById("config");
const seccionActivo = document.getElementById("seccionActivo");
const inputNombre = document.getElementById("nombreEmpleado");
const btnIniciar = document.getElementById("btnIniciar");
const btnDetener = document.getElementById("btnDetener");
const video = document.getElementById("video");
const nombreActivo = document.getElementById("nombreActivo");
const idEstacion = document.getElementById("idEstacion");

const CLAVE_NOMBRE = "qamonitor.nombreEmpleado";
const CLAVE_ESTACION = "qamonitor.estacionId";
let pc = null;
let stream = null;

function setEstado(texto, tipo = "neutro") {
  subtitulo.textContent = texto;
  punto.className = "punto" + (tipo === "conectado" ? " conectado" : tipo === "error" ? " error" : "");
}

function mostrarPanelActivo(mostrar) {
  config.classList.toggle("oculto", mostrar);
  seccionActivo.classList.toggle("oculto", !mostrar);
}

async function iniciarMonitoreo(nombreEmpleado) {
  btnIniciar.disabled = true;
  setEstado("Solicitando cámara y micrófono…");

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, frameRate: 15 },
      audio: { echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    setEstado("No se pudo acceder a cámara/micrófono: " + err.message, "error");
    btnIniciar.disabled = false;
    return;
  }

  video.srcObject = stream;

  // Config minima de ICE para red local; agregar servidores STUN/TURN si se sale de la LAN.
  pc = new RTCPeerConnection({ iceServers: [] });
  stream.getTracks().forEach((track) => pc.addTrack(track, stream));

  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "connected") {
      setEstado("Sesión activa · transmitiendo en vivo", "conectado");
    } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
      setEstado("Conexión perdida. Reintentando…", "error");
      setTimeout(() => iniciarMonitoreo(nombreEmpleado), 3000);
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
        empleado_nombre: nombreEmpleado,
        // Si ya hay un id de estacion guardado de una sesion anterior en este mismo equipo,
        // se reutiliza para que el supervisor vea una sola estacion por puesto de trabajo
        // en vez de una nueva cada vez que se reconecta (ej. tras cerrar y volver a abrir).
        estacion_id: localStorage.getItem(CLAVE_ESTACION) || undefined,
      }),
    });
  } catch (err) {
    setEstado("No se pudo contactar al servidor: " + err.message, "error");
    btnIniciar.disabled = false;
    return;
  }

  if (!respuesta.ok) {
    setEstado("El servidor rechazó la conexión (código " + respuesta.status + ")", "error");
    btnIniciar.disabled = false;
    return;
  }

  const datos = await respuesta.json();
  await pc.setRemoteDescription({ sdp: datos.sdp, type: datos.type });
  localStorage.setItem(CLAVE_ESTACION, datos.estacion_id);

  nombreActivo.textContent = nombreEmpleado;
  idEstacion.textContent = datos.estacion_id;
  mostrarPanelActivo(true);
  setEstado("Sesión activa · transmitiendo en vivo", "conectado");
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
  mostrarPanelActivo(false);
  btnIniciar.disabled = false;
  setEstado("Sesión finalizada. Ingresa tu nombre para reiniciar.");
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

btnIniciar.addEventListener("click", () => {
  const nombre = inputNombre.value.trim();
  if (!nombre) {
    setEstado("Escribe tu nombre para continuar", "error");
    return;
  }
  localStorage.setItem(CLAVE_NOMBRE, nombre);
  iniciarMonitoreo(nombre);
});

btnDetener.addEventListener("click", detenerMonitoreo);

// El programa de escritorio (ver desktop_client/app.py) abre esta pagina con
// ?estacion_id=...&nombre=... como parametros de URL: el id viene de un archivo que el
// propio programa guarda junto a si mismo en el PC (estable entre reinicios, no depende
// del cache del navegador embebido), y el nombre es opcional si se preconfiguro el puesto.
// Si vienen en la URL tienen prioridad sobre lo guardado en localStorage, que solo sirve
// como respaldo para cuando se accede desde un navegador normal sin el programa.
window.addEventListener("DOMContentLoaded", () => {
  const parametros = new URLSearchParams(window.location.search);
  const estacionIdDelPrograma = parametros.get("estacion_id");
  const nombreDelPrograma = parametros.get("nombre");

  if (estacionIdDelPrograma) {
    localStorage.setItem(CLAVE_ESTACION, estacionIdDelPrograma);
  }

  const nombreInicial = nombreDelPrograma || localStorage.getItem(CLAVE_NOMBRE);
  if (nombreInicial) {
    inputNombre.value = nombreInicial;
    localStorage.setItem(CLAVE_NOMBRE, nombreInicial);
    iniciarMonitoreo(nombreInicial);
  } else {
    setEstado("Ingresa tu nombre para iniciar la sesión de monitoreo");
  }
});
