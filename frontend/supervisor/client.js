// Pagina "Centro de Monitoreo": KPIs + lista de empleados conectados (al elegir uno se ve su
// camara en vivo, via snapshot JPEG que refresca solo) + timeline general. La conexión/autenticación/estado en vivo vienen de
// core.js (compartido con el resto de páginas del panel).

const gridEstacionesEl = document.getElementById("gridEstaciones");
const feedEl = document.getElementById("feed");
const vacioEl = document.getElementById("vacio");
const buscadorEl = document.getElementById("buscador");
const contadorTerminalesEl = document.getElementById("contadorTerminales");

const kpiConectadas = document.getElementById("kpiConectadas");
const kpiCapacidad = document.getElementById("kpiCapacidad");
const kpiTranscripciones = document.getElementById("kpiTranscripciones");
const kpiLenguaje = document.getElementById("kpiLenguaje");
const kpiLenguajeUltimo = document.getElementById("kpiLenguajeUltimo");
const kpiGestos = document.getElementById("kpiGestos");
const kpiSinIncidentes = document.getElementById("kpiSinIncidentes");
const kpiPendientes = document.getElementById("kpiPendientes");
const contadorFiltroPendientes = document.getElementById("contadorFiltroPendientes");
const contadorFiltroConectadas = document.getElementById("contadorFiltroConectadas");
const contadorFiltroDesconectadas = document.getElementById("contadorFiltroDesconectadas");

const TIPOS_CRITICOS = new Set(["alerta_lenguaje", "alerta_postura", "alerta_expresion", "alerta_ausencia"]);
const MAX_EVENTOS_TIMELINE = 60;

let filtroBusqueda = "";
// El monitoreo en tiempo real es lo prioritario: por defecto solo se muestran las camaras
// conectadas ahora mismo, no las desconectadas (que solo sirven para revisar historial y ya
// tienen su propio filtro/pagina para eso).
let filtroVista = "conectadas"; // todas | pendientes | conectadas | desconectadas
let filtroTimeline = "todos";
let capacidadMaxima = null;

function renderizarTodo() {
  renderizarKPIs();
  renderizarGrid();
  renderizarFeed();
}

function renderizarKPIs() {
  const { estaciones, contadores } = Core;
  const activas = [...estaciones.values()].filter((e) => e.conectada);
  kpiConectadas.textContent = activas.length;
  kpiCapacidad.textContent = `/${capacidadMaxima || activas.length}`;
  kpiTranscripciones.textContent = `${contadores.transcripciones} frases transcritas hoy`;

  kpiLenguaje.textContent = contadores.porTipo.alerta_lenguaje || 0;
  const ultimoLenguaje = [...estaciones.values()]
    .flatMap((e) => e.eventos)
    .filter((e) => e.tipo === "alerta_lenguaje")
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
  kpiLenguajeUltimo.textContent = ultimoLenguaje ? `Último evento: ${Core.hace(ultimoLenguaje.timestamp)}` : "Sin eventos aún";

  kpiGestos.textContent = (contadores.porTipo.alerta_expresion || 0) + (contadores.porTipo.alerta_ausencia || 0);
  const sinIncidentes = activas.filter((e) => e.pendientes === 0 && e.eventos.every((ev) => !TIPOS_CRITICOS.has(ev.tipo) || ev.veredicto === "falsa_alarma")).length;
  kpiSinIncidentes.textContent = `${sinIncidentes} de ${activas.length} estaciones sin incidentes`;

  kpiPendientes.textContent = contadores.pendientes;
  contadorFiltroPendientes.textContent = contadores.pendientes;
  contadorFiltroConectadas.textContent = activas.length;
  contadorFiltroDesconectadas.textContent = estaciones.size - activas.length;

  contadorTerminalesEl.textContent = `${activas.length} puesto${activas.length === 1 ? "" : "s"}`;
}

function estacionesFiltradas() {
  return [...Core.estaciones.entries()]
    .filter(([id, datos]) => {
      if (filtroBusqueda) {
        const texto = (datos.empleado || "") + " " + id;
        if (!texto.toLowerCase().includes(filtroBusqueda)) return false;
      }
      if (filtroVista === "pendientes") return datos.pendientes > 0;
      if (filtroVista === "conectadas") return datos.conectada;
      if (filtroVista === "desconectadas") return !datos.conectada;
      return true;
    })
    .sort(([, a], [, b]) => {
      if (a.pendientes !== b.pendientes) return b.pendientes - a.pendientes;
      if (a.conectada !== b.conectada) return a.conectada ? -1 : 1;
      return (a.empleado || "").localeCompare(b.empleado || "");
    });
}

const MENSAJES_VACIO = {
  todas: "Todavía no se ha conectado ninguna estación.",
  pendientes: "Ninguna estación tiene alertas pendientes por revisar.",
  conectadas: "No hay cámaras conectadas en este momento.",
  desconectadas: "No hay estaciones desconectadas en el historial.",
};

// Estacion cuyo video se ve en el visor. Se recuerda al navegar entre paginas del panel.
const CLAVE_VISOR = "qamonitor.visorEstacion";
let seleccionada = sessionStorage.getItem(CLAVE_VISOR);
const visorEl = document.getElementById("visorEstacion");

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Lista compacta: solo nombres (con sede/modulo y estado). La camara se ve al hacer clic, asi
// no se llena la pantalla de videos cuando hay muchos empleados conectados.
function renderizarGrid() {
  const filas = estacionesFiltradas();
  vacioEl.textContent = MENSAJES_VACIO[filtroVista] || MENSAJES_VACIO.todas;
  vacioEl.classList.toggle("oculto", filas.length > 0);

  gridEstacionesEl.innerHTML = filas
    .map(([id, datos]) => {
      const nombre = datos.empleado || "Sin identificar";
      const subtitulo = [datos.sede, datos.modulo].filter(Boolean).join(" · ") || "Sin sede / módulo";
      const clases = ["fila-empleado", id === seleccionada ? "seleccionada" : "", datos.pendientes > 0 ? "con-alerta" : ""].join(" ");
      return `
        <button class="${clases}" data-ver="${escapar(id)}" type="button" title="Ver la cámara de ${escapar(nombre)}">
          <div class="avatar-estacion" style="background:${Core.colorAvatar(id)}">${Core.iniciales(nombre)}</div>
          <div class="flex flex-col min-w-0 flex-1">
            <span class="nombre-empleado font-body-md text-body-md font-semibold text-on-surface truncate">${escapar(nombre)}</span>
            <span class="font-label-sm text-label-sm text-on-surface-variant truncate">${escapar(subtitulo)}</span>
          </div>
          ${datos.pausa ? `<span class="chip-pausa"><span class="material-symbols-outlined text-[13px]">${datos.pausa.tipo === "almuerzo" ? "restaurant" : "coffee"}</span>${datos.pausa.tipo === "almuerzo" ? "Almuerzo" : "Break"}</span>` : ""}
          ${datos.pendientes > 0 ? `<span class="badge-pendientes-mini" title="Alertas pendientes">${datos.pendientes}</span>` : ""}
          <span class="punto-estado ${datos.pausa ? "en-pausa" : datos.conectada ? "en-vivo" : ""}" title="${datos.pausa ? Core.textoPausa(datos.pausa) : datos.conectada ? "En vivo" : "Desconectada"}"></span>
        </button>`;
    })
    .join("");
  renderizarVisor();
}

gridEstacionesEl.addEventListener("click", (ev) => {
  const fila = ev.target.closest("[data-ver]");
  if (!fila) return;
  seleccionada = fila.dataset.ver;
  sessionStorage.setItem(CLAVE_VISOR, seleccionada);
  renderizarGrid();
});

// El visor se arma una sola vez por estacion elegida (el <img> no se recrea en cada evento,
// para que el video no parpadee); en cada evento solo se actualizan los datos de alrededor.
let visorDe = null;

function renderizarVisor() {
  const datos = seleccionada ? Core.estaciones.get(seleccionada) : null;
  if (!datos) {
    visorDe = null;
    visorEl.innerHTML = `
      <div class="visor-vacio">
        <span class="material-symbols-outlined text-[44px] text-primary">touch_app</span>
        <span class="font-headline-sm text-headline-sm text-on-surface">Selecciona un empleado</span>
        <span class="font-body-sm text-body-sm">Haz clic en un nombre de la lista para ver su cámara en tiempo real.</span>
      </div>`;
    return;
  }

  const nombre = datos.empleado || "Sin identificar";
  const clave = `${seleccionada}|${datos.conectada}|${datos.pausa ? datos.pausa.tipo + datos.pausa.inicio : ""}`;
  if (visorDe !== clave) {
    visorDe = clave;
    visorEl.className = "tarjeta-estacion";
    visorEl.innerHTML = `
      <div class="cabecera">
        <div class="flex items-center gap-2 min-w-0">
          <div class="avatar-estacion" style="background:${Core.colorAvatar(seleccionada)}">${Core.iniciales(nombre)}</div>
          <div class="flex flex-col min-w-0">
            <span class="font-headline-sm text-headline-sm text-white truncate" data-visor="nombre"></span>
            <span class="font-label-sm text-label-sm text-white/70 truncate" data-visor="subtitulo"></span>
          </div>
        </div>
        <div class="flex items-center gap-1 shrink-0" data-visor="estado"></div>
      </div>
      <div class="video-wrap" data-estacion-pausa="${escapar(seleccionada)}">
        ${datos.pausa
          ? Core.htmlPausa(datos.pausa)
          : datos.conectada
          ? `<img alt="Video en vivo de ${escapar(nombre)}" data-estacion="${escapar(seleccionada)}" src="${Core.conToken(`/api/estaciones/${seleccionada}/snapshot.jpg?t=${Date.now()}`)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'" />
             <div class="sin-senal" style="display:none"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Esperando primer cuadro…</span></div>`
          : `<div class="sin-senal"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Sin conexión</span></div>`}
      </div>
      <div class="cuerpo">
        <div class="flex items-center justify-between gap-2 flex-wrap">
          <span data-visor="emocion"></span>
          <button type="button" class="btn-veredicto btn-enfocar w-max" data-enfocar="${escapar(seleccionada)}">
            <span class="material-symbols-outlined text-[14px] align-middle">center_focus_strong</span>
            Abrir centro de control
          </button>
        </div>
        <div data-visor="ultimo"></div>
      </div>`;
  }

  visorEl.classList.toggle("con-alerta", datos.pendientes > 0);
  visorEl.querySelector('[data-visor="nombre"]').textContent = nombre;
  visorEl.querySelector('[data-visor="subtitulo"]').textContent = [datos.sede, datos.modulo].filter(Boolean).join(" · ") || seleccionada;
  visorEl.querySelector('[data-visor="estado"]').innerHTML = `
    ${datos.pendientes > 0 ? `<span class="badge-pendientes-mini">${datos.pendientes}</span>` : ""}
    <span class="flex items-center gap-1 bg-white/15 px-2 py-0.5 rounded-full">
      <span class="w-2 h-2 rounded-full ${datos.conectada ? "bg-secondary-container animate-pulse" : "bg-outline"}"></span>
      <span class="font-label-sm text-label-sm text-white">${datos.pausa ? "EN PAUSA" : datos.conectada ? "EN VIVO" : "DESCONECTADA"}</span>
    </span>`;
  visorEl.querySelector('[data-visor="emocion"]').innerHTML = datos.conectada && !datos.pausa
    ? `<span class="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider mr-2">Emoción actual</span><span data-emocion="${escapar(seleccionada)}">${Core.chipEmocion(datos.emocion)}</span>`
    : "";
  const ultimo = visorEl.querySelector('[data-visor="ultimo"]');
  ultimo.innerHTML = "";
  if (datos.eventos[0]) ultimo.appendChild(Core.crearElementoEvento(datos.eventos[0], false, renderizarTodo));
  else ultimo.innerHTML = '<p class="vacio-feed">Sin actividad todavía.</p>';
}

// "Abrir centro de control": guarda el foco (para que Transcripciones/Lenguaje/Gestos tambien
// puedan filtrar por esta estacion) y abre la vista unificada de esa estacion.
visorEl.addEventListener("click", (ev) => {
  const boton = ev.target.closest("[data-enfocar]");
  if (!boton) return;
  Core.establecerFoco(boton.dataset.enfocar);
  window.location.href = `estacion.html?id=${encodeURIComponent(boton.dataset.enfocar)}`;
});

// Refresca solo el video del visor cada 150ms (~6-7fps visibles): el backend genera el snapshot
// a ~10fps. Como ya no hay una miniatura por empleado, el panel no descarga N videos a la vez.
setInterval(() => {
  const img = visorEl.querySelector(".video-wrap img[data-estacion]");
  if (!img) return;
  img.src = Core.conToken(`/api/estaciones/${img.dataset.estacion}/snapshot.jpg?t=${Date.now()}`);
  img.style.display = "";
  if (img.nextElementSibling) img.nextElementSibling.style.display = "none";
}, 150);

function renderizarFeed() {
  feedEl.innerHTML = "";

  const combinado = [];
  for (const [id, datos] of Core.estaciones) {
    for (const evento of datos.eventos) combinado.push({ ...evento, estacion_id: evento.estacion_id || id });
  }
  combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const filtrado = filtroTimeline === "todos" ? combinado : combinado.filter((e) => e.tipo === filtroTimeline);

  for (const evento of filtrado.slice(0, MAX_EVENTOS_TIMELINE)) {
    feedEl.appendChild(Core.crearElementoEvento(evento, true, renderizarTodo));
  }
  if (filtrado.length === 0) {
    feedEl.innerHTML = '<p class="vacio-feed">Sin actividad todavía.</p>';
  }
}

buscadorEl.addEventListener("input", () => {
  filtroBusqueda = buscadorEl.value.trim().toLowerCase();
  renderizarGrid();
});

document.querySelectorAll(".filtro-vista").forEach((btn) => {
  btn.addEventListener("click", () => {
    filtroVista = btn.dataset.filtro;
    document.querySelectorAll(".filtro-vista").forEach((b) => b.classList.toggle("activo", b === btn));
    renderizarGrid();
  });
});
document.querySelector('.filtro-vista[data-filtro="conectadas"]').classList.add("activo");

document.querySelectorAll(".filtro-timeline").forEach((btn) => {
  btn.addEventListener("click", () => {
    filtroTimeline = btn.dataset.tipo;
    document.querySelectorAll(".filtro-timeline").forEach((b) => b.classList.toggle("activo", b === btn));
    renderizarFeed();
  });
});
document.querySelector('.filtro-timeline[data-tipo="todos"]').classList.add("activo");

async function cargarCapacidadMaxima() {
  try {
    const resp = await fetch("/api/salud");
    const datos = await resp.json();
    capacidadMaxima = datos.max_estaciones_concurrentes;
    renderizarKPIs();
  } catch (err) {
    // se queda mostrando el numero de conectadas como referencia
  }
}

Core.onEvento((evento) => {
  // La emocion llega cada pocos segundos por estacion: se actualiza solo su etiqueta, sin
  // redibujar el grid completo (eso recrearia los <img> del video y lo haria parpadear).
  if (evento.tipo === "emocion") {
    const chip = document.querySelector(`[data-emocion="${evento.estacion_id}"]`);
    if (chip) chip.innerHTML = Core.chipEmocion(Core.estaciones.get(evento.estacion_id)?.emocion);
    return;
  }
  renderizarTodo();
});
Core.onListo(renderizarTodo);
Core.iniciar(() => {
  cargarCapacidadMaxima();
  renderizarTodo();
});
