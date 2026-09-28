// Pagina "Gestos y Expresiones": alertas de expresión facial negativa y de ausencia (la
// deteccion de "movimiento brusco"/postura se elimino por falsos positivos -moverse en la
// silla, agacharse, bajar la cabeza-, pero las alertas viejas de ese tipo siguen apareciendo
// aqui si existen en el historial), con botones de veredicto.

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

// Pestañas: "negativas" (expresion negativa, ausencia y postura vieja; se califican con fue
// real / falsa alarma) y "positivas" (felicidad >= 60%; informativas, solo se eliminan).
const TIPOS_POR_GRUPO = {
  negativas: new Set(["alerta_expresion", "alerta_ausencia", "alerta_postura"]),
  positivas: new Set(["alerta_expresion_positiva"]),
};
let grupoActivo = "negativas";
document.querySelectorAll(".tab-expresiones").forEach((tab) =>
  tab.addEventListener("click", () => {
    grupoActivo = tab.dataset.grupo;
    document.querySelectorAll(".tab-expresiones").forEach((t) => t.classList.toggle("activo", t === tab));
    renderizar();
  })
);

function eventosDeGrupo(grupo, foco) {
  const lista = [];
  for (const [id, datos] of Core.estaciones) {
    if (foco && id !== foco) continue;
    for (const evento of datos.eventos) {
      if (TIPOS_POR_GRUPO[grupo].has(evento.tipo)) lista.push({ ...evento, estacion_id: evento.estacion_id || id });
    }
  }
  return lista;
}

function renderizar() {
  actualizarBannerFoco();
  const foco = Core.obtenerFoco();
  document.getElementById("conteoNegativas").textContent = eventosDeGrupo("negativas", foco).filter((e) => !e.veredicto).length;
  document.getElementById("conteoPositivas").textContent = eventosDeGrupo("positivas", foco).length;
  const combinado = eventosDeGrupo(grupoActivo, foco);
  combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const filtrado = filtroBusqueda
    ? combinado.filter((e) => {
        const nombre = Core.estaciones.get(e.estacion_id)?.empleado || e.estacion_id;
        return (nombre + " " + e.detalle).toLowerCase().includes(filtroBusqueda);
      })
    : combinado;

  if (grupoActivo === "negativas") {
    const pendientes = combinado.filter((e) => !e.veredicto).length;
    contadorAlertasEl.textContent =
      `${combinado.length} expresión${combinado.length === 1 ? "" : "es"} negativa${combinado.length === 1 ? "" : "s"}` +
      (pendientes ? ` · ${pendientes} sin revisar` : "");
  } else {
    contadorAlertasEl.textContent = `${combinado.length} expresión${combinado.length === 1 ? "" : "es"} positiva${combinado.length === 1 ? "" : "s"}`;
  }

  feedEl.innerHTML = "";
  for (const evento of filtrado.slice(0, 200)) {
    feedEl.appendChild(Core.crearElementoEvento(evento, true, renderizar));
  }
  if (filtrado.length === 0) {
    feedEl.innerHTML = `<p class="vacio-feed">${grupoActivo === "negativas" ? "Sin expresiones negativas todavía." : "Sin expresiones positivas todavía."}</p>`;
  }
}

buscadorEl.addEventListener("input", () => {
  filtroBusqueda = buscadorEl.value.trim().toLowerCase();
  renderizar();
});

Core.onEvento((e) => { if (e.tipo !== "emocion") renderizar(); });
Core.onListo(renderizar);
Core.iniciar(renderizar);
