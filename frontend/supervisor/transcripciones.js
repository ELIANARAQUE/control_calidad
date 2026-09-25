// Pagina "Transcripciones": todas las frases transcritas por Whisper, de todas las
// estaciones, mas recientes primero.

const feedEl = document.getElementById("feed");
const contadorTranscripcionesEl = document.getElementById("contadorTranscripciones");
const buscadorEl = document.getElementById("buscador");
let filtroBusqueda = "";

// Cuando hay varias camaras hablando a la vez, mezclar todas las transcripciones en un solo
// feed se vuelve dificil de seguir. `Core.obtenerFoco()` (guardado en sessionStorage desde el
// boton "Monitorear solo esta" del Centro de Monitoreo) permite quedarse viendo solo una
// estacion hasta que el supervisor decida quitar el filtro.
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
      if (evento.tipo === "transcripcion") combinado.push({ ...evento, estacion_id: evento.estacion_id || id });
    }
  }
  combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const filtrado = filtroBusqueda
    ? combinado.filter((e) => {
        const nombre = Core.estaciones.get(e.estacion_id)?.empleado || e.estacion_id;
        return (nombre + " " + e.texto).toLowerCase().includes(filtroBusqueda);
      })
    : combinado;

  contadorTranscripcionesEl.textContent = `${combinado.length} frase${combinado.length === 1 ? "" : "s"} transcrita${combinado.length === 1 ? "" : "s"}`;

  feedEl.innerHTML = "";
  for (const evento of filtrado.slice(0, 200)) {
    feedEl.appendChild(Core.crearElementoEvento(evento, true, renderizar));
  }
  if (filtrado.length === 0) {
    feedEl.innerHTML = '<p class="vacio-feed">Sin transcripciones todavía.</p>';
  }
}

buscadorEl.addEventListener("input", () => {
  filtroBusqueda = buscadorEl.value.trim().toLowerCase();
  renderizar();
});

Core.onEvento(renderizar);
Core.onListo(renderizar);
Core.iniciar(renderizar);
