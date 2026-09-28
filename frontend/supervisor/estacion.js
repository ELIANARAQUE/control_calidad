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

// Si la misma computadora se reconecta varias veces (mismo estacion_id, otro dia u otra hora),
// sin esto se mezclaban en un solo feed las alertas/transcripciones de TODAS esas sesiones,
// lo que se veia como "alertas viejas" o "de otra camara". Se limita a la sesion mas reciente.
let sesionInicio = null;
let sesionFin = null;
let mostrandoHistorialCompleto = false;

async function cargarSesion() {
  try {
    const resp = await Core.apiFetch(`/api/estaciones/${estacionId}/sesion`);
    if (!resp.ok) return;
    const datos = await resp.json();
    sesionInicio = datos.inicio;
    sesionFin = datos.fin;
  } catch (err) {
    // sin limite de sesion: se muestra todo el historial de la estacion
  }
}

function dentroDeLaSesionActual(evento) {
  if (mostrandoHistorialCompleto || !sesionInicio) return true;
  if (evento.timestamp < sesionInicio) return false;
  if (sesionFin && evento.timestamp > sesionFin) return false;
  return true;
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
  const pausa = datos?.pausa;
  estadoConexionEstacionEl.innerHTML = `
    <span class="w-2 h-2 rounded-full ${pausa ? "bg-[#f59e0b]" : conectada ? "bg-secondary-container animate-pulse" : "bg-outline"}"></span>
    <span class="font-label-sm text-label-sm">${pausa ? "EN PAUSA" : conectada ? "EN VIVO" : "DESCONECTADA"}</span>
  `;

  videoWrapEl.dataset.estacionPausa = estacionId;
  if (pausa) {
    const marca = `${pausa.tipo}|${pausa.inicio}`;
    if (videoWrapEl.dataset.pausa !== marca) {
      videoWrapEl.dataset.pausa = marca;
      videoWrapEl.innerHTML = Core.htmlPausa(pausa);
    }
    return;
  }
  delete videoWrapEl.dataset.pausa;
  if (videoWrapEl.querySelector(".pausa-senal")) videoWrapEl.innerHTML = "";

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

function actualizarBannerSesion() {
  let banner = document.getElementById("bannerSesion");
  if (!sesionInicio) {
    banner?.remove();
    return;
  }
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "bannerSesion";
    banner.className = "flex items-center justify-between gap-space-sm bg-primary/10 text-primary px-space-md py-space-sm rounded-lg mb-space-sm font-label-md text-label-md font-semibold";
    feedEl.parentElement.insertBefore(banner, feedEl);
  }
  banner.innerHTML = mostrandoHistorialCompleto
    ? `<span class="flex items-center gap-space-xs"><span class="material-symbols-outlined text-[18px]">history</span>Mostrando el historial completo de esta estación (puede incluir sesiones anteriores)</span>
       <button type="button" id="btnSoloSesionActual" class="underline">Ver solo la sesión actual</button>`
    : `<span class="flex items-center gap-space-xs"><span class="material-symbols-outlined text-[18px]">schedule</span>Mostrando solo la sesión que empezó ${Core.hace(sesionInicio)}</span>
       <button type="button" id="btnHistorialCompleto" class="underline">Ver historial completo</button>`;
  const btn = document.getElementById("btnSoloSesionActual") || document.getElementById("btnHistorialCompleto");
  btn.addEventListener("click", () => {
    mostrandoHistorialCompleto = !mostrandoHistorialCompleto;
    renderizar();
  });
}

function renderizar() {
  if (!estacionId) return;
  renderizarCabecera();
  renderizarEmocion();
  actualizarBannerSesion();

  const datos = Core.estaciones.get(estacionId);
  const eventos = (datos?.eventos || []).filter(dentroDeLaSesionActual);

  statPendientes.textContent = eventos.filter((e) => !e.veredicto && e.alerta_id != null).length;
  statTranscripciones.textContent = eventos.filter((e) => e.tipo === "transcripcion").length;
  statGestos.textContent = eventos.filter((e) => e.tipo === "alerta_postura" || e.tipo === "alerta_expresion" || e.tipo === "alerta_ausencia").length;
  statLenguaje.textContent = eventos.filter((e) => e.tipo === "alerta_lenguaje").length;

  feedEl.innerHTML = "";
  for (const evento of eventos.slice(0, 200)) {
    feedEl.appendChild(Core.crearElementoEvento(evento, false, renderizar));
  }
  if (eventos.length === 0) {
    feedEl.innerHTML = '<p class="vacio-feed">Sin actividad todavía para esta estación.</p>';
  }
}

function renderizarEmocion() {
  const el = document.getElementById("emocionActual");
  if (el) el.innerHTML = Core.chipEmocion(Core.estaciones.get(estacionId)?.emocion);
}

Core.onEvento((evento) => {
  if (evento.estacion_id !== estacionId) return;
  if (evento.tipo === "emocion") return renderizarEmocion();
  renderizar();
});
Core.onListo(async () => {
  await cargarSesion();
  renderizar();
});
Core.iniciar(renderizar);
