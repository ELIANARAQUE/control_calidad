// Pagina "Estación" (centro de control unificado de una sola persona): video, alertas de
// postura/expresión, lenguaje y transcripciones, todo junto, para cuando hay varias cámaras
// conectadas a la vez y el supervisor quiere concentrarse en un solo empleado sin ruido de
// las demás. Se llega aquí desde el botón "Monitorear solo esta" del Centro de Monitoreo.

const params = new URLSearchParams(location.search);
const estacionId = params.get("id");

const feedEl = document.getElementById("feed");
const nombreEstacionEl = document.getElementById("nombreEstacion");
const detalleEstacionEl = document.getElementById("detalleEstacion");
const subtituloEstacionEl = document.getElementById("subtituloEstacion");
const avatarEstacionEl = document.getElementById("avatarEstacion");
const estadoConexionEstacionEl = document.getElementById("estadoConexionEstacion");
const videoWrapEl = document.getElementById("videoWrapEstacion");
const statPendientes = document.getElementById("statPendientes");
const statTranscripciones = document.getElementById("statTranscripciones");
const statGestos = document.getElementById("statGestos");
const statLenguaje = document.getElementById("statLenguaje");

if (!estacionId) {
  document.querySelector("main").innerHTML =
    '<div class="p-space-lg"><p class="font-body-md text-body-md text-error">No se especificó ninguna estación (falta ?id= en la URL). Vuelve al Centro de Monitoreo y usa "Monitorear solo esta".</p></div>';
}

function renderizarCabecera() {
  const datos = Core.estaciones.get(estacionId);
  const nombre = datos?.empleado || "Sin identificar";
  nombreEstacionEl.textContent = nombre;
  detalleEstacionEl.textContent = [datos?.sede, datos?.modulo].filter(Boolean).join(" · ") || estacionId;
  subtituloEstacionEl.textContent = `Estación ${estacionId.slice(0, 8)}…`;
  avatarEstacionEl.textContent = Core.iniciales(nombre);
  avatarEstacionEl.style.background = Core.colorAvatar(estacionId);

  const conectada = !!datos?.conectada;
  estadoConexionEstacionEl.innerHTML = `
    <span class="w-2 h-2 rounded-full ${conectada ? "bg-secondary-container animate-pulse" : "bg-outline"}"></span>
    <span class="font-label-sm text-label-sm">${conectada ? "EN VIVO" : "DESCONECTADA"}</span>
  `;

  if (conectada) {
    if (!videoWrapEl.querySelector("img")) {
      videoWrapEl.innerHTML = `<img alt="Video en vivo de ${nombre}" id="imgVideoEstacion" src="${Core.conToken(`/api/estaciones/${estacionId}/snapshot.jpg?t=${Date.now()}`)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'" />
        <div class="sin-senal" style="display:none"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Esperando primer cuadro…</span></div>`;
    }
  } else if (!videoWrapEl.querySelector(".sin-senal") || videoWrapEl.querySelector("img")) {
    videoWrapEl.innerHTML = '<div class="sin-senal"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Sin conexión</span></div>';
  }
}

setInterval(() => {
  const img = document.getElementById("imgVideoEstacion");
  if (img) img.src = Core.conToken(`/api/estaciones/${estacionId}/snapshot.jpg?t=${Date.now()}`);
}, 150);

function renderizar() {
  if (!estacionId) return;
  renderizarCabecera();

  const datos = Core.estaciones.get(estacionId);
  const eventos = datos?.eventos || [];

  statPendientes.textContent = datos?.pendientes || 0;
  statTranscripciones.textContent = eventos.filter((e) => e.tipo === "transcripcion").length;
  statGestos.textContent = eventos.filter((e) => e.tipo === "alerta_postura" || e.tipo === "alerta_expresion").length;
  statLenguaje.textContent = eventos.filter((e) => e.tipo === "alerta_lenguaje").length;

  feedEl.innerHTML = "";
  for (const evento of eventos.slice(0, 200)) {
    feedEl.appendChild(Core.crearElementoEvento(evento, false, renderizar));
  }
  if (eventos.length === 0) {
    feedEl.innerHTML = '<p class="vacio-feed">Sin actividad todavía para esta estación.</p>';
  }
}

Core.onEvento((evento) => {
  if (evento.estacion_id === estacionId) renderizar();
});
Core.onListo(renderizar);
Core.iniciar(renderizar);
