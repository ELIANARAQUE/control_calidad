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

// Si el programa de escritorio ya conoce el nombre del empleado (sesion anterior),
// se autocompleta y arranca solo, sin que el empleado tenga que interactuar.
window.addEventListener("DOMContentLoaded", () => {
  const nombreGuardado = localStorage.getItem(CLAVE_NOMBRE);
  if (nombreGuardado) {
    inputNombre.value = nombreGuardado;
    iniciarMonitoreo(nombreGuardado);
  } else {
    setEstado("Ingresa tu nombre para iniciar la sesión de monitoreo");
  }
});
