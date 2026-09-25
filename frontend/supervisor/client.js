// Pagina "Centro de Monitoreo": KPIs + grid de estaciones en vivo (video vía snapshot JPEG
// que refresca solo) + timeline general. La conexión/autenticación/estado en vivo vienen de
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

const TIPOS_CRITICOS = new Set(["alerta_lenguaje", "alerta_postura", "alerta_expresion"]);
const MAX_EVENTOS_TIMELINE = 60;

let filtroBusqueda = "";
let filtroVista = "todas"; // todas | pendientes | conectadas
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

  kpiGestos.textContent = (contadores.porTipo.alerta_postura || 0) + (contadores.porTipo.alerta_expresion || 0);
  const sinIncidentes = activas.filter((e) => e.pendientes === 0 && e.eventos.every((ev) => !TIPOS_CRITICOS.has(ev.tipo) || ev.veredicto === "falsa_alarma")).length;
  kpiSinIncidentes.textContent = `${sinIncidentes} de ${activas.length} estaciones sin incidentes`;

  kpiPendientes.textContent = contadores.pendientes;
  contadorFiltroPendientes.textContent = contadores.pendientes;

  vacioEl.classList.toggle("oculto", estaciones.size > 0);
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
      return true;
    })
    .sort(([, a], [, b]) => {
      if (a.pendientes !== b.pendientes) return b.pendientes - a.pendientes;
      if (a.conectada !== b.conectada) return a.conectada ? -1 : 1;
      return (a.empleado || "").localeCompare(b.empleado || "");
    });
}

function renderizarGrid() {
  gridEstacionesEl.innerHTML = "";
  const filas = estacionesFiltradas();

  for (const [id, datos] of filas) {
    const nombre = datos.empleado || "Sin identificar";
    const tienePendientes = datos.pendientes > 0;
    const ultimoEvento = datos.eventos[0];
    const card = document.createElement("article");
    card.className = "tarjeta-estacion" + (tienePendientes ? " con-alerta" : "");

    const subtitulo = [datos.sede, datos.modulo].filter(Boolean).join(" · ") || id;

    card.innerHTML = `
      <div class="cabecera">
        <div class="flex items-center gap-2 min-w-0">
          <div class="avatar-estacion" style="background:${Core.colorAvatar(id)}">${Core.iniciales(nombre)}</div>
          <div class="flex flex-col min-w-0">
            <span class="font-headline-sm text-headline-sm text-white truncate">${nombre}</span>
            <span class="font-label-sm text-label-sm text-white/70 truncate">${subtitulo}</span>
          </div>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          ${tienePendientes ? `<span class="badge-pendientes-mini">${datos.pendientes}</span>` : ""}
          <span class="flex items-center gap-1 bg-white/15 px-2 py-0.5 rounded-full">
            <span class="w-2 h-2 rounded-full ${datos.conectada ? "bg-secondary-container animate-pulse" : "bg-outline"}"></span>
            <span class="font-label-sm text-label-sm text-white">${datos.conectada ? "EN VIVO" : "DESCONECTADA"}</span>
          </span>
        </div>
      </div>
      <div class="video-wrap">
        ${datos.conectada
          ? `<img alt="Video en vivo de ${nombre}" data-estacion="${id}" src="${Core.conToken(`/api/estaciones/${id}/snapshot.jpg?t=${Date.now()}`)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'" />
             <div class="sin-senal" style="display:none"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Esperando primer cuadro…</span></div>`
          : `<div class="sin-senal"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Sin conexión</span></div>`
        }
      </div>
      <div class="cuerpo">
        ${ultimoEvento ? "" : '<p class="vacio-feed">Sin actividad todavía.</p>'}
      </div>
    `;

    if (ultimoEvento) {
      card.querySelector(".cuerpo").appendChild(Core.crearElementoEvento(ultimoEvento, false, renderizarTodo));
    }

    gridEstacionesEl.appendChild(card);
  }
}

// Refresca las miniaturas de video cada 400ms (~2.5fps visibles): el backend ahora genera el
// snapshot con cada frame que llega de la camara, no solo a los ~3fps de YOLO, asi que vale
// la pena pedirlo mas seguido para que el panel se vea fluido y no "congelado".
setInterval(() => {
  document.querySelectorAll(".video-wrap img[data-estacion]").forEach((img) => {
    const id = img.dataset.estacion;
    img.src = Core.conToken(`/api/estaciones/${id}/snapshot.jpg?t=${Date.now()}`);
    img.style.display = "";
    if (img.nextElementSibling) img.nextElementSibling.style.display = "none";
  });
}, 400);

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
document.querySelector('.filtro-vista[data-filtro="todas"]').classList.add("activo");

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

Core.onEvento(renderizarTodo);
Core.onListo(renderizarTodo);
Core.iniciar(() => {
  cargarCapacidadMaxima();
  renderizarTodo();
});
