// Cliente del panel de supervisor: lista compacta de estaciones a la izquierda (escala a
// 12-15 conectadas sin volverse un muro de tarjetas) + feed de la seleccionada a la derecha.

const estadoTextoEl = document.getElementById("estadoTexto");
const puntoEl = document.getElementById("punto");
const listaEstacionesEl = document.getElementById("listaEstaciones");
const feedEl = document.getElementById("feed");
const vacioEl = document.getElementById("vacio");
const buscadorEl = document.getElementById("buscador");
const tituloDetalleEl = document.getElementById("tituloDetalle");
const subtituloDetalleEl = document.getElementById("subtituloDetalle");

const statEstaciones = document.getElementById("statEstaciones");
const statAlertas = document.getElementById("statAlertas");
const statPendientes = document.getElementById("statPendientes");
const statTranscripciones = document.getElementById("statTranscripciones");

const TIPOS_CON_VEREDICTO = new Set(["alerta_postura", "alerta_lenguaje", "alerta_expresion"]);
const MAX_EVENTOS_POR_ESTACION = 20;
const MAX_EVENTOS_FEED_TODAS = 40;
const COLORES_AVATAR = ["#1f5f4f", "#6d28d9", "#1d4ed8", "#b45309", "#c2410c", "#0f766e", "#7c3aed"];

// estacion_id -> { empleado, conectada, pendientes, eventos: [...] (mas reciente primero) }
const estaciones = new Map();
const contadores = { alertasHoy: 0, pendientes: 0, transcripciones: 0 };
let seleccionId = null; // null = vista "Todas"
let filtroBusqueda = "";

function conectar() {
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocolo}://${location.host}/ws/supervisor`);

  ws.onopen = () => {
    estadoTextoEl.textContent = "Conectado en vivo";
    puntoEl.classList.add("conectado");
  };
  ws.onclose = () => {
    estadoTextoEl.textContent = "Desconectado. Reintentando…";
    puntoEl.classList.remove("conectado");
    setTimeout(conectar, 3000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (msg) => procesarEvento(JSON.parse(msg.data));
}

function obtenerEstacion(estacionId) {
  if (!estaciones.has(estacionId)) {
    estaciones.set(estacionId, { empleado: null, conectada: false, pendientes: 0, eventos: [] });
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
        estacion.pendientes++;
      }
      estacion.eventos.unshift(evento);
  }

  if (estacion.eventos.length > MAX_EVENTOS_POR_ESTACION) {
    estacion.eventos.length = MAX_EVENTOS_POR_ESTACION;
  }

  renderizarTodo();
}

function colorAvatar(estacionId) {
  let hash = 0;
  for (let i = 0; i < estacionId.length; i++) hash = (hash * 31 + estacionId.charCodeAt(i)) >>> 0;
  return COLORES_AVATAR[hash % COLORES_AVATAR.length];
}

function iniciales(nombre) {
  if (!nombre) return "?";
  const partes = nombre.trim().split(/\s+/);
  return (partes[0][0] + (partes[1]?.[0] || "")).toUpperCase();
}

function renderizarTodo() {
  renderizarResumen();
  renderizarLista();
  renderizarFeed();
}

function renderizarResumen() {
  const activas = [...estaciones.values()].filter((e) => e.conectada).length;
  statEstaciones.textContent = activas;
  statAlertas.textContent = contadores.alertasHoy;
  statPendientes.textContent = contadores.pendientes;
  statTranscripciones.textContent = contadores.transcripciones;
  vacioEl.classList.toggle("oculto", estaciones.size > 0);
}

function ordenEstaciones() {
  // Prioridad: quien tiene alertas sin revisar primero, luego conectados, luego por nombre.
  return [...estaciones.entries()]
    .filter(([id, datos]) => {
      if (!filtroBusqueda) return true;
      const texto = (datos.empleado || "") + " " + id;
      return texto.toLowerCase().includes(filtroBusqueda);
    })
    .sort(([, a], [, b]) => {
      if (a.pendientes !== b.pendientes) return b.pendientes - a.pendientes;
      if (a.conectada !== b.conectada) return a.conectada ? -1 : 1;
      return (a.empleado || "").localeCompare(b.empleado || "");
    });
}

function renderizarLista() {
  const filaTodas = `
    <div class="fila-estacion todas ${seleccionId === null ? "activa" : ""}" data-id="">
      <div class="avatar" style="background:#3a3833">Σ</div>
      <div class="info-fila">
        <div class="nombre-fila">Todas las estaciones</div>
        <div class="detalle-fila">${estaciones.size} conectada(s) en total</div>
      </div>
    </div>
  `;

  const filas = ordenEstaciones()
    .map(([id, datos]) => {
      const nombre = datos.empleado || "Sin identificar";
      return `
        <div class="fila-estacion ${seleccionId === id ? "activa" : ""}" data-id="${id}">
          <div class="avatar" style="background:${colorAvatar(id)}">${iniciales(nombre)}</div>
          <div class="info-fila">
            <div class="nombre-fila">${nombre}</div>
            <div class="detalle-fila">
              <span class="punto-mini ${datos.conectada ? "en-vivo" : ""}"></span>
              ${datos.conectada ? "En vivo" : "Desconectada"}
            </div>
          </div>
          ${datos.pendientes > 0 ? `<span class="badge-pendientes">${datos.pendientes}</span>` : ""}
        </div>
      `;
    })
    .join("");

  listaEstacionesEl.innerHTML = filaTodas + filas;

  listaEstacionesEl.querySelectorAll(".fila-estacion").forEach((fila) => {
    fila.addEventListener("click", () => {
      seleccionId = fila.dataset.id || null;
      renderizarTodo();
    });
  });
}

function textoEvento(evento) {
  switch (evento.tipo) {
    case "alerta_postura":
      return { icono: "⚠️", texto: evento.detalle };
    case "alerta_lenguaje":
      return { icono: "🤬", texto: evento.detalle };
    case "alerta_expresion":
      return { icono: "😠", texto: evento.detalle };
    case "transcripcion":
      return { icono: "🎤", texto: `"${evento.texto}"` };
    case "conexion":
      return { icono: "✅", texto: `${evento.empleado} se conectó` };
    case "desconexion":
      return { icono: "🔌", texto: "Estación desconectada" };
    default:
      return { icono: "•", texto: evento.detalle || JSON.stringify(evento) };
  }
}

async function enviarVeredicto(estacionId, alertaId, veredicto, contenedorAcciones) {
  contenedorAcciones.innerHTML = "Guardando…";
  try {
    const resp = await fetch(`/api/alertas/${alertaId}/veredicto`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ veredicto }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);

    // Se guarda el veredicto EN el evento original (el que vive dentro de estaciones.get(id).eventos),
    // no solo en el DOM: si no se guarda ahi, la proxima vez que se re-renderice el feed
    // (por ejemplo al llegar cualquier otro evento nuevo) se reconstruye desde cero y
    // "olvida" que ya se habia contestado, mostrando los botones de nuevo.
    const estacion = estaciones.get(estacionId);
    const eventoOriginal = estacion?.eventos.find((e) => e.alerta_id === alertaId);
    if (eventoOriginal) eventoOriginal.veredicto = veredicto;

    contadores.pendientes = Math.max(0, contadores.pendientes - 1);
    if (estacion) estacion.pendientes = Math.max(0, estacion.pendientes - 1);
    renderizarTodo();
  } catch (err) {
    contenedorAcciones.textContent = "Error al guardar: " + err.message;
  }
}

function crearElementoEvento(evento, mostrarTagEstacion) {
  const { icono, texto } = textoEvento(evento);
  const div = document.createElement("div");
  div.className = "item-evento " + evento.tipo;

  const hora = new Date(evento.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const nombreEstacion = estaciones.get(evento.estacion_id)?.empleado || evento.estacion_id;
  const tagEstacion = mostrarTagEstacion ? `<span class="tag-estacion">${nombreEstacion}</span>` : "";

  div.innerHTML = `
    <div class="icono-evento">${icono}</div>
    <div class="cuerpo-evento">
      <div class="texto-evento">${texto}</div>
      <div class="meta-evento">${tagEstacion}<span>${hora}</span></div>
    </div>
  `;

  if (TIPOS_CON_VEREDICTO.has(evento.tipo) && evento.alerta_id != null) {
    const acciones = document.createElement("div");
    acciones.className = "acciones";

    if (evento.veredicto) {
      acciones.innerHTML = evento.veredicto === "confirmada" ? "✔ Marcada como real" : "✘ Falsa alarma";
    } else {
      const btnConfirmar = document.createElement("button");
      btnConfirmar.textContent = "Fue real";
      btnConfirmar.className = "btn-veredicto btn-confirmar";
      btnConfirmar.onclick = () => enviarVeredicto(evento.estacion_id, evento.alerta_id, "confirmada", acciones);

      const btnDescartar = document.createElement("button");
      btnDescartar.textContent = "Falsa alarma";
      btnDescartar.className = "btn-veredicto btn-descartar";
      btnDescartar.onclick = () => enviarVeredicto(evento.estacion_id, evento.alerta_id, "falsa_alarma", acciones);

      acciones.appendChild(btnConfirmar);
      acciones.appendChild(btnDescartar);
    }
    div.querySelector(".cuerpo-evento").appendChild(acciones);
  }

  return div;
}

function renderizarFeed() {
  feedEl.innerHTML = "";

  if (seleccionId === null) {
    tituloDetalleEl.textContent = "Todas las estaciones";
    subtituloDetalleEl.textContent = "Actividad combinada, más reciente primero";

    const combinado = [];
    for (const [id, datos] of estaciones) {
      for (const evento of datos.eventos) combinado.push({ ...evento, estacion_id: evento.estacion_id || id });
    }
    combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    for (const evento of combinado.slice(0, MAX_EVENTOS_FEED_TODAS)) {
      feedEl.appendChild(crearElementoEvento(evento, true));
    }
    if (combinado.length === 0 && estaciones.size > 0) {
      feedEl.innerHTML = '<p class="vacio">Sin actividad todavía.</p>';
    }
    return;
  }

  const datos = estaciones.get(seleccionId);
  if (!datos) return;

  tituloDetalleEl.textContent = datos.empleado || "Sin identificar";
  subtituloDetalleEl.textContent = seleccionId + (datos.conectada ? " · en vivo" : " · desconectada");

  if (datos.eventos.length === 0) {
    feedEl.innerHTML = '<p class="vacio">Sin actividad todavía.</p>';
    return;
  }
  for (const evento of datos.eventos) {
    feedEl.appendChild(crearElementoEvento(evento, false));
  }
}

buscadorEl.addEventListener("input", () => {
  filtroBusqueda = buscadorEl.value.trim().toLowerCase();
  renderizarLista();
});

conectar();
