// Cliente del panel de supervisor: recibe alertas/transcripciones en vivo por WebSocket y
// las organiza en una tarjeta por estación (en vez de un único listado largo).

const estadoTextoEl = document.getElementById("estadoTexto");
const puntoEl = document.getElementById("punto");
const gridEl = document.getElementById("grid");
const vacioEl = document.getElementById("vacio");

const statEstaciones = document.getElementById("statEstaciones");
const statAlertas = document.getElementById("statAlertas");
const statPendientes = document.getElementById("statPendientes");
const statTranscripciones = document.getElementById("statTranscripciones");

const TIPOS_CON_VEREDICTO = new Set(["alerta_postura", "alerta_lenguaje", "alerta_expresion"]);
const MAX_EVENTOS_POR_TARJETA = 12;

// estacion_id -> { empleado, conectada, eventos: [...] (mas reciente primero) }
const estaciones = new Map();

const contadores = { alertasHoy: 0, pendientes: 0, transcripciones: 0 };

function conectar() {
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocolo}://${location.host}/ws/supervisor`);

  ws.onopen = () => {
    estadoTextoEl.textContent = "Conectado en vivo";
    puntoEl.classList.add("conectado");
  };
  ws.onclose = () => {
    estadoTextoEl.textContent = "Desconectado. Reintentando en 3s…";
    puntoEl.classList.remove("conectado");
    setTimeout(conectar, 3000);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = (msg) => {
    const evento = JSON.parse(msg.data);
    procesarEvento(evento);
  };
}

function obtenerEstacion(estacionId) {
  if (!estaciones.has(estacionId)) {
    estaciones.set(estacionId, { empleado: null, conectada: false, eventos: [] });
  }
  return estaciones.get(estacionId);
}

function procesarEvento(evento) {
  const estacion = obtenerEstacion(evento.estacion_id);

  switch (evento.tipo) {
    case "conexion":
      estacion.empleado = evento.empleado;
      estacion.conectada = true;
      break;
    case "desconexion":
      estacion.conectada = false;
      break;
    case "transcripcion":
      contadores.transcripciones++;
      estacion.eventos.unshift(evento);
      break;
    default:
      if (TIPOS_CON_VEREDICTO.has(evento.tipo)) {
        contadores.alertasHoy++;
        contadores.pendientes++;
      }
      estacion.eventos.unshift(evento);
  }

  if (estacion.eventos.length > MAX_EVENTOS_POR_TARJETA) {
    estacion.eventos.length = MAX_EVENTOS_POR_TARJETA;
  }

  actualizarResumen();
  renderizarTarjeta(evento.estacion_id);
}

function actualizarResumen() {
  const activas = [...estaciones.values()].filter((e) => e.conectada).length;
  statEstaciones.textContent = activas;
  statAlertas.textContent = contadores.alertasHoy;
  statPendientes.textContent = contadores.pendientes;
  statTranscripciones.textContent = contadores.transcripciones;

  vacioEl.classList.toggle("oculto", estaciones.size > 0);
}

function textoEvento(evento) {
  switch (evento.tipo) {
    case "alerta_postura":
      return `⚠ ${evento.detalle}`;
    case "alerta_lenguaje":
      return `🤬 ${evento.detalle}`;
    case "alerta_expresion":
      return `😠 ${evento.detalle}`;
    case "transcripcion":
      return `🎤 "${evento.texto}"`;
    default:
      return evento.detalle || JSON.stringify(evento);
  }
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
    contenedorAcciones.innerHTML = veredicto === "confirmada" ? "✔ Marcada como real" : "✘ Falsa alarma";
    contadores.pendientes = Math.max(0, contadores.pendientes - 1);
    statPendientes.textContent = contadores.pendientes;
  } catch (err) {
    contenedorAcciones.textContent = "Error al guardar: " + err.message;
  }
}

function crearElementoEvento(evento) {
  const div = document.createElement("div");
  div.className = "evento " + evento.tipo;

  const hora = new Date(evento.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  div.innerHTML = `<div class="texto-evento">${textoEvento(evento)}</div><div class="meta">${hora}</div>`;

  if (TIPOS_CON_VEREDICTO.has(evento.tipo) && evento.alerta_id != null) {
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

  return div;
}

function renderizarTarjeta(estacionId) {
  const datos = estaciones.get(estacionId);
  let tarjeta = document.getElementById("estacion-" + estacionId);

  if (!tarjeta) {
    tarjeta = document.createElement("article");
    tarjeta.className = "tarjeta-estacion";
    tarjeta.id = "estacion-" + estacionId;
    tarjeta.innerHTML = `
      <div class="cabecera-estacion">
        <div>
          <div class="nombre-empleado"></div>
          <div class="id-estacion"></div>
        </div>
        <span class="chip-estado"></span>
      </div>
      <div class="lista-eventos"></div>
    `;
    gridEl.appendChild(tarjeta);
  }

  tarjeta.querySelector(".nombre-empleado").textContent = datos.empleado || "Empleado sin identificar";
  tarjeta.querySelector(".id-estacion").textContent = estacionId;

  const chip = tarjeta.querySelector(".chip-estado");
  chip.textContent = datos.conectada ? "En vivo" : "Desconectada";
  chip.className = "chip-estado " + (datos.conectada ? "en-vivo" : "desconectada");

  const lista = tarjeta.querySelector(".lista-eventos");
  lista.innerHTML = "";
  if (datos.eventos.length === 0) {
    lista.innerHTML = '<div class="sin-eventos">Sin actividad todavía.</div>';
  } else {
    for (const evento of datos.eventos) {
      lista.appendChild(crearElementoEvento(evento));
    }
  }
}

conectar();
