// Pagina "Detección de Lenguaje": solo las alertas de lenguaje inapropiado, con botones de
// veredicto (fue real / falsa alarma) para que el supervisor las revise una por una.

const feedEl = document.getElementById("feed");
const contadorAlertasEl = document.getElementById("contadorAlertas");
const buscadorEl = document.getElementById("buscador");
let filtroBusqueda = "";

// Ver "Monitorear solo esta" en transcripciones.js: mismo mecanismo de foco por estacion,
// guardado en sessionStorage, para no mezclar las alertas de varias camaras a la vez.
function actualizarBannerFoco() {
  let banner = document.getElementById("bannerFoco");
  const foco = Core.obtenerFoco();
  if (!foco) {
    banner?.remove();
    return;
  }
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "bannerFoco";
    banner.className = "flex items-center justify-between gap-space-sm bg-primary/10 text-primary px-space-md py-space-sm rounded-lg mb-space-sm font-label-md text-label-md font-semibold";
    feedEl.parentElement.insertBefore(banner, feedEl);
  }
  const nombre = Core.estaciones.get(foco)?.empleado || foco;
  banner.innerHTML = `
    <span class="flex items-center gap-space-xs"><span class="material-symbols-outlined text-[18px]">center_focus_strong</span>Monitoreando solo a: ${nombre}</span>
    <button type="button" id="btnQuitarFoco" class="underline">Ver todas las estaciones</button>
  `;
  document.getElementById("btnQuitarFoco").addEventListener("click", () => {
    Core.quitarFoco();
    actualizarBannerFoco();
    renderizar();
  });
}

function renderizar() {
  actualizarBannerFoco();
  const foco = Core.obtenerFoco();
  const combinado = [];
  for (const [id, datos] of Core.estaciones) {
    if (foco && id !== foco) continue;
    for (const evento of datos.eventos) {
      if (evento.tipo === "alerta_lenguaje") combinado.push({ ...evento, estacion_id: evento.estacion_id || id });
    }
  }
  combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const filtrado = filtroBusqueda
    ? combinado.filter((e) => {
        const nombre = Core.estaciones.get(e.estacion_id)?.empleado || e.estacion_id;
        return (nombre + " " + e.detalle).toLowerCase().includes(filtroBusqueda);
      })
    : combinado;

  const pendientes = combinado.filter((e) => !e.veredicto).length;
  contadorAlertasEl.textContent = `${combinado.length} alerta${combinado.length === 1 ? "" : "s"} de lenguaje` + (pendientes ? ` · ${pendientes} sin revisar` : "");

  feedEl.innerHTML = "";
  for (const evento of filtrado.slice(0, 200)) {
    feedEl.appendChild(Core.crearElementoEvento(evento, true, renderizar));
  }
  if (filtrado.length === 0) {
    feedEl.innerHTML = '<p class="vacio-feed">Sin alertas de lenguaje todavía.</p>';
  }
}

buscadorEl.addEventListener("input", () => {
  filtroBusqueda = buscadorEl.value.trim().toLowerCase();
  renderizar();
});

Core.onEvento(renderizar);
Core.onListo(renderizar);
Core.iniciar(renderizar);
