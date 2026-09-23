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

function agregarEvento(evento) {
  const div = document.createElement("div");
  div.className = "evento " + evento.tipo;

  const hora = new Date(evento.timestamp).toLocaleTimeString();
  let texto = "";
  switch (evento.tipo) {
    case "alerta_postura":
      texto = `⚠ Alerta: ${evento.detalle}`;
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
  eventosEl.prepend(div);

  // Evita que el DOM crezca indefinidamente en una jornada larga
  while (eventosEl.children.length > 200) {
    eventosEl.removeChild(eventosEl.lastChild);
  }
}

conectar();
