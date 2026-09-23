// Cliente del panel de supervisor: recibe alertas/transcripciones en vivo por WebSocket.

const estadoEl = document.getElementById("estado");
const eventosEl = document.getElementById("eventos");

function conectar() {
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocolo}://${location.host}/ws/supervisor`);

  ws.onopen = () => (estadoEl.textContent = "Conectado en vivo");
  ws.onclose = () => {
    estadoEl.textContent = "Desconectado. Reintentando en 3s...";
    setTimeout(conectar, 3000);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = (msg) => {
    const evento = JSON.parse(msg.data);
    agregarEvento(evento);
  };
}

async function enviarVeredicto(alertaId, veredicto, contenedorAcciones) {
  contenedorAcciones.innerHTML = "Guardando…";
  try {
    const resp = await fetch(`/api/alertas/${alertaId}/veredicto`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ veredicto }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    contenedorAcciones.innerHTML =
      veredicto === "confirmada" ? "✔ Marcada como real" : "✘ Marcada como falsa alarma";
  } catch (err) {
    contenedorAcciones.textContent = "Error al guardar: " + err.message;
  }
}

function agregarEvento(evento) {
  const div = document.createElement("div");
  div.className = "evento " + evento.tipo;

  const hora = new Date(evento.timestamp).toLocaleTimeString();
  let texto = "";
  switch (evento.tipo) {
    case "alerta_postura":
      texto = `⚠ Alerta: ${evento.detalle}`;
      break;
    case "alerta_lenguaje":
      texto = `🤬 Alerta: ${evento.detalle}`;
      break;
    case "alerta_expresion":
      texto = `😠 Alerta: ${evento.detalle}`;
      break;
    case "transcripcion":
      texto = `🎤 "${evento.texto}"`;
      break;
    case "conexion":
      texto = `✅ ${evento.empleado} se conecto`;
      break;
    case "desconexion":
      texto = `❌ ${evento.empleado} se desconecto`;
      break;
    default:
      texto = JSON.stringify(evento);
  }

  div.innerHTML = `<div>${texto}</div><div class="meta">Estacion ${evento.estacion_id} · ${hora}</div>`;

  // Las alertas de postura llevan botones para confirmar o descartar: esas etiquetas
  // se guardan en el servidor y con el tiempo forman el dataset para entrenar un modelo.
  const esAlertaConVeredicto = ["alerta_postura", "alerta_lenguaje", "alerta_expresion"].includes(evento.tipo);
  if (esAlertaConVeredicto && evento.alerta_id != null) {
    const acciones = document.createElement("div");
    acciones.className = "acciones";

    const btnConfirmar = document.createElement("button");
    btnConfirmar.textContent = "Fue real";
    btnConfirmar.className = "btn-veredicto btn-confirmar";
    btnConfirmar.onclick = () => enviarVeredicto(evento.alerta_id, "confirmada", acciones);

    const btnDescartar = document.createElement("button");
    btnDescartar.textContent = "Falsa alarma";
    btnDescartar.className = "btn-veredicto btn-descartar";
    btnDescartar.onclick = () => enviarVeredicto(evento.alerta_id, "falsa_alarma", acciones);

    acciones.appendChild(btnConfirmar);
    acciones.appendChild(btnDescartar);
    div.appendChild(acciones);
  }

  eventosEl.prepend(div);

  // Evita que el DOM crezca indefinidamente en una jornada larga
  while (eventosEl.children.length > 200) {
    eventosEl.removeChild(eventosEl.lastChild);
  }
}

conectar();
