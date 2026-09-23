// Cliente ligero: captura camara/microfono y establece una conexion WebRTC con el servidor.
// No hace ningun procesamiento de IA en el navegador (el PC del empleado es de baja potencia).

const video = document.getElementById("video");
const estadoEl = document.getElementById("estado");
const btnIniciar = document.getElementById("btnIniciar");
const inputNombre = document.getElementById("nombreEmpleado");

let pc = null;

function setEstado(texto) {
  estadoEl.textContent = texto;
}

async function iniciarMonitoreo() {
  const nombreEmpleado = inputNombre.value.trim() || "Empleado sin nombre";
  btnIniciar.disabled = true;
  setEstado("Solicitando camara y microfono...");

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, frameRate: 15 },
      audio: { echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    setEstado("Error al acceder a camara/microfono: " + err.message);
    btnIniciar.disabled = false;
    return;
  }

  video.srcObject = stream;

  // Config minima de ICE para red local; agregar servidores STUN/TURN si se sale de la LAN.
  pc = new RTCPeerConnection({ iceServers: [] });

  stream.getTracks().forEach((track) => pc.addTrack(track, stream));

  pc.onconnectionstatechange = () => {
    setEstado("Estado de conexion: " + pc.connectionState);
  };

  setEstado("Negociando conexion WebRTC...");

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // Espera a que termine la recoleccion de candidatos ICE (patron simple, sin trickle ICE)
  await esperarIceCompleto(pc);

  const respuesta = await fetch("/api/offer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
      empleado_nombre: nombreEmpleado,
    }),
  });

  if (!respuesta.ok) {
    setEstado("Error del servidor: " + respuesta.status);
    btnIniciar.disabled = false;
    return;
  }

  const datos = await respuesta.json();
  await pc.setRemoteDescription({ sdp: datos.sdp, type: datos.type });

  setEstado("Conectado - estacion " + datos.estacion_id);
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

btnIniciar.addEventListener("click", iniciarMonitoreo);
