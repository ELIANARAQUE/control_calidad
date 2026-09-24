// Cliente del panel de supervisor: sidebar + topbar + KPIs + grid de estaciones en vivo
// (video vía snapshot JPEG que refresca solo, más el resto de la telemetría) + timeline
// filtrable + controles de supervisión (sensibilidad de lenguaje, avisos, informe CSV).

const estadoTextoEl = document.getElementById("estadoTexto");
const puntoEl = document.getElementById("punto");
const gridEstacionesEl = document.getElementById("gridEstaciones");
const feedEl = document.getElementById("feed");
const vacioEl = document.getElementById("vacio");
const buscadorEl = document.getElementById("buscador");
const contadorTerminalesEl = document.getElementById("contadorTerminales");
const relojTexto = document.getElementById("relojTexto");
const toastEl = document.getElementById("toast");

const kpiConectadas = document.getElementById("kpiConectadas");
const kpiCapacidad = document.getElementById("kpiCapacidad");
const kpiTranscripciones = document.getElementById("kpiTranscripciones");
const kpiLenguaje = document.getElementById("kpiLenguaje");
const kpiLenguajeUltimo = document.getElementById("kpiLenguajeUltimo");
const kpiGestos = document.getElementById("kpiGestos");
const kpiSinIncidentes = document.getElementById("kpiSinIncidentes");
const kpiPendientes = document.getElementById("kpiPendientes");
const contadorFiltroPendientes = document.getElementById("contadorFiltroPendientes");
const badgeCampana = document.getElementById("badgeCampana");

const TIPOS_CON_VEREDICTO = new Set(["alerta_postura", "alerta_lenguaje", "alerta_expresion"]);
const TIPOS_CRITICOS = new Set(["alerta_lenguaje", "alerta_postura", "alerta_expresion"]);
const MAX_EVENTOS_POR_ESTACION = 30;
const MAX_EVENTOS_TIMELINE = 60;
const COLORES_AVATAR = ["#0f9d68", "#6d28d9", "#1d4ed8", "#b45309", "#0f766e", "#7c3aed", "#0891b2"];

// estacion_id -> { empleado, sede, modulo, conectada, pendientes, eventos: [...] (mas reciente primero) }
const estaciones = new Map();
const contadores = { alertasHoy: 0, pendientes: 0, transcripciones: 0, porTipo: { alerta_postura: 0, alerta_lenguaje: 0, alerta_expresion: 0 } };
let filtroBusqueda = "";
let filtroVista = "todas"; // todas | pendientes | conectadas
let filtroTimeline = "todos";
let nivelSensibilidad = "estricto";

// --- Autenticación del panel (usuario/clave compartido, ver app/core/auth.py) ---
const CLAVE_TOKEN = "qamonitor.supervisor.token";
let tokenSesion = sessionStorage.getItem(CLAVE_TOKEN);

function conToken(url) {
  if (!tokenSesion) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(tokenSesion);
}

function apiFetch(url, opciones = {}) {
  const headers = { ...(opciones.headers || {}) };
  if (tokenSesion) headers["X-Auth-Token"] = tokenSesion;
  return fetch(url, { ...opciones, headers });
}

function mostrarToast(texto) {
  toastEl.textContent = texto;
  toastEl.classList.remove("oculto");
  clearTimeout(mostrarToast._t);
  mostrarToast._t = setTimeout(() => toastEl.classList.add("oculto"), 3500);
}

function conectar() {
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(conToken(`${protocolo}://${location.host}/ws/supervisor`));

  ws.onopen = () => {
    estadoTextoEl.textContent = "Conectado en vivo";
    puntoEl.classList.add("conectado");
  };
  ws.onclose = (ev) => {
    if (ev.code === 4401) {
      cerrarSesionLocal("Tu sesión expiró o el servidor se reinició. Ingresa de nuevo.");
      return;
    }
    estadoTextoEl.textContent = "Desconectado. Reintentando…";
    puntoEl.classList.remove("conectado");
    setTimeout(conectar, 3000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (msg) => procesarEvento(JSON.parse(msg.data));
}

async function cargarEstacionesActivas() {
  try {
    const resp = await apiFetch("/api/estaciones");
    if (resp.status === 401) return cerrarSesionLocal("Tu sesión expiró. Ingresa de nuevo.");
    if (!resp.ok) return;
    const lista = await resp.json();
    for (const item of lista) {
      const estacion = obtenerEstacion(item.estacion_id);
      estacion.empleado = item.empleado_nombre;
      estacion.sede = item.sede;
      estacion.modulo = item.modulo;
      estacion.conectada = true;
    }
    renderizarTodo();
  } catch (err) {
    // El panel sigue funcionando solo con lo que llegue por WebSocket a partir de ahora.
  }
}

async function cargarSensibilidad() {
  try {
    const resp = await fetch("/api/config/sensibilidad");
    if (!resp.ok) return;
    const datos = await resp.json();
    nivelSensibilidad = datos.nivel;
    actualizarBotonesSensibilidad();
  } catch (err) {
    // valor por defecto ya seteado
  }
}

function actualizarBotonesSensibilidad() {
  document.querySelectorAll(".btn-sensibilidad, .btn-sensibilidad-panel").forEach((btn) => {
    btn.classList.toggle("activo", btn.dataset.nivel === nivelSensibilidad);
  });
  document.getElementById("sensibilidadTexto").textContent = nivelSensibilidad;
  document.getElementById("sensibilidadPanelTexto").textContent = nivelSensibilidad.toUpperCase();
}

async function cambiarSensibilidad(nivel) {
  try {
    const resp = await apiFetch("/api/config/sensibilidad", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nivel }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    nivelSensibilidad = nivel;
    actualizarBotonesSensibilidad();
    mostrarToast(`Sensibilidad de lenguaje actualizada a "${nivel}"`);
  } catch (err) {
    mostrarToast("No se pudo actualizar la sensibilidad: " + err.message);
  }
}

function obtenerEstacion(estacionId) {
  if (!estaciones.has(estacionId)) {
    estaciones.set(estacionId, {
      empleado: null, sede: null, modulo: null, conectada: false, pendientes: 0, eventos: [],
    });
  }
  return estaciones.get(estacionId);
}

function procesarEvento(evento) {
  const estacion = obtenerEstacion(evento.estacion_id);

  switch (evento.tipo) {
    case "conexion":
      estacion.empleado = evento.empleado;
      estacion.sede = evento.sede || estacion.sede;
      estacion.modulo = evento.modulo || estacion.modulo;
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
        contadores.porTipo[evento.tipo] = (contadores.porTipo[evento.tipo] || 0) + 1;
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

function hace(timestampIso) {
  const segundos = Math.max(0, Math.round((Date.now() - new Date(timestampIso).getTime()) / 1000));
  if (segundos < 5) return "justo ahora";
  if (segundos < 60) return `hace ${segundos}s`;
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `hace ${minutos}m`;
  return `hace ${Math.round(minutos / 60)}h`;
}

function renderizarTodo() {
  renderizarKPIs();
  renderizarGrid();
  renderizarFeed();
}

function renderizarKPIs() {
  const activas = [...estaciones.values()].filter((e) => e.conectada);
  kpiConectadas.textContent = activas.length;
  kpiCapacidad.textContent = `/${window.__capacidadMaxima || activas.length}`;
  kpiTranscripciones.textContent = `${contadores.transcripciones} frases transcritas hoy`;

  kpiLenguaje.textContent = contadores.porTipo.alerta_lenguaje || 0;
  const ultimoLenguaje = [...estaciones.values()]
    .flatMap((e) => e.eventos)
    .filter((e) => e.tipo === "alerta_lenguaje")
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];
  kpiLenguajeUltimo.textContent = ultimoLenguaje ? `Último evento: ${hace(ultimoLenguaje.timestamp)}` : "Sin eventos aún";

  kpiGestos.textContent = (contadores.porTipo.alerta_postura || 0) + (contadores.porTipo.alerta_expresion || 0);
  const sinIncidentes = activas.filter((e) => e.pendientes === 0 && e.eventos.every((ev) => !TIPOS_CRITICOS.has(ev.tipo) || ev.veredicto === "falsa_alarma")).length;
  kpiSinIncidentes.textContent = `${sinIncidentes} de ${activas.length} estaciones sin incidentes`;

  kpiPendientes.textContent = contadores.pendientes;
  contadorFiltroPendientes.textContent = contadores.pendientes;
  if (contadores.pendientes > 0) {
    badgeCampana.textContent = contadores.pendientes;
    badgeCampana.classList.remove("hidden");
    badgeCampana.classList.add("flex");
  } else {
    badgeCampana.classList.add("hidden");
  }

  vacioEl.classList.toggle("oculto", estaciones.size > 0);
  contadorTerminalesEl.textContent = `${activas.length} puesto${activas.length === 1 ? "" : "s"}`;
}

function estacionesFiltradas() {
  return [...estaciones.entries()]
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

function textoEvento(evento) {
  switch (evento.tipo) {
    case "alerta_postura":
      return { icono: "warning", texto: evento.detalle, etiqueta: "Postura" };
    case "alerta_lenguaje":
      return { icono: "gavel", texto: evento.detalle, etiqueta: "Lenguaje" };
    case "alerta_expresion":
      return { icono: "sentiment_dissatisfied", texto: evento.detalle, etiqueta: "Expresión" };
    case "transcripcion":
      return { icono: "record_voice_over", texto: `"${evento.texto}"`, etiqueta: "Transcripción" };
    case "conexion":
      return { icono: "login", texto: `${evento.empleado} se conectó${evento.sede ? " · " + evento.sede : ""}`, etiqueta: "Conexión" };
    case "desconexion":
      return { icono: "logout", texto: "Estación desconectada", etiqueta: "Desconexión" };
    default:
      return { icono: "info", texto: evento.detalle || JSON.stringify(evento), etiqueta: "Evento" };
  }
}

async function enviarVeredicto(estacionId, alertaId, veredicto, contenedorAcciones) {
  contenedorAcciones.innerHTML = "Guardando…";
  try {
    const resp = await apiFetch(`/api/alertas/${alertaId}/veredicto`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ veredicto }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);

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

function crearElementoEvento(evento, mostrarNombreEstacion) {
  const { icono, texto, etiqueta } = textoEvento(evento);
  const div = document.createElement("div");
  const esCritico = evento.tipo === "alerta_lenguaje" || evento.tipo === "alerta_postura" || evento.tipo === "alerta_expresion";
  div.className = "item-evento" + (esCritico && evento.veredicto !== "falsa_alarma" ? " critico" : "");

  const hora = new Date(evento.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const nombreEstacion = estaciones.get(evento.estacion_id)?.empleado || evento.estacion_id;

  div.innerHTML = `
    <div class="fila-superior">
      <span class="hora">${hora}</span>
      ${mostrarNombreEstacion ? `<span class="nombre">${nombreEstacion}</span>` : ""}
      <span class="etiqueta"><span class="material-symbols-outlined text-[11px] align-middle">${icono}</span> ${etiqueta}</span>
    </div>
    <div class="flex items-start gap-2">
      ${evento.captura_url ? `<a href="${conToken(evento.captura_url)}" target="_blank" rel="noopener" title="Ver captura completa"><img src="${conToken(evento.captura_url)}" class="captura-mini" alt="Captura del momento de la alerta" /></a>` : ""}
      <p class="texto flex-1">${texto}</p>
    </div>
  `;

  if (TIPOS_CON_VEREDICTO.has(evento.tipo) && evento.alerta_id != null) {
    const acciones = document.createElement("div");
    acciones.className = "acciones";

    if (evento.veredicto) {
      acciones.innerHTML = evento.veredicto === "confirmada"
        ? '<span class="text-error font-semibold text-xs">✔ Marcada como real</span>'
        : '<span class="text-secondary font-semibold text-xs">✘ Falsa alarma</span>';
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
    div.appendChild(acciones);
  }

  return div;
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
          <div class="avatar-estacion" style="background:${colorAvatar(id)}">${iniciales(nombre)}</div>
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
          ? `<img alt="Video en vivo de ${nombre}" data-estacion="${id}" src="${conToken(`/api/estaciones/${id}/snapshot.jpg?t=${Date.now()}`)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'" />
             <div class="sin-senal" style="display:none"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Esperando primer cuadro…</span></div>`
          : `<div class="sin-senal"><span class="material-symbols-outlined text-[32px]">videocam_off</span><span>Sin conexión</span></div>`
        }
      </div>
      <div class="cuerpo">
        ${ultimoEvento ? "" : '<p class="vacio-feed">Sin actividad todavía.</p>'}
      </div>
    `;

    if (ultimoEvento) {
      card.querySelector(".cuerpo").appendChild(crearElementoEvento(ultimoEvento, false));
    }

    gridEstacionesEl.appendChild(card);
  }
}

// Refresca las miniaturas de video cada 2s (la conexion WebRTC ya entrega frames a ~3fps
// al backend; refrescar el <img> mas rapido que eso no aportaria nada).
setInterval(() => {
  document.querySelectorAll(".video-wrap img[data-estacion]").forEach((img) => {
    const id = img.dataset.estacion;
    img.src = conToken(`/api/estaciones/${id}/snapshot.jpg?t=${Date.now()}`);
    img.style.display = "";
    if (img.nextElementSibling) img.nextElementSibling.style.display = "none";
  });
}, 2000);

function renderizarFeed() {
  feedEl.innerHTML = "";

  const combinado = [];
  for (const [id, datos] of estaciones) {
    for (const evento of datos.eventos) combinado.push({ ...evento, estacion_id: evento.estacion_id || id });
  }
  combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  const filtrado = filtroTimeline === "todos" ? combinado : combinado.filter((e) => e.tipo === filtroTimeline);

  for (const evento of filtrado.slice(0, MAX_EVENTOS_TIMELINE)) {
    feedEl.appendChild(crearElementoEvento(evento, true));
  }
  if (filtrado.length === 0) {
    feedEl.innerHTML = '<p class="vacio-feed">Sin actividad todavía.</p>';
  }
}

// --- Reloj local ---
function actualizarReloj() {
  relojTexto.textContent = new Date().toLocaleTimeString("es-CO", { hour12: false });
}
setInterval(actualizarReloj, 1000);
actualizarReloj();

// --- Filtros de vista / búsqueda ---
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

// --- Navegación lateral: scroll suave + atajos que también filtran el timeline ---
document.querySelectorAll(".nav-link[data-target]").forEach((link) => {
  link.addEventListener("click", (ev) => {
    ev.preventDefault();
    document.getElementById(link.dataset.target)?.scrollIntoView({ behavior: "smooth" });
  });
});
document.querySelectorAll(".nav-link[data-filtro]").forEach((link) => {
  link.addEventListener("click", (ev) => {
    ev.preventDefault();
    const tipo = link.dataset.filtro;
    const btn = document.querySelector(`.filtro-timeline[data-tipo="${tipo}"]`);
    if (btn) btn.click();
    document.getElementById("seccion-timeline")?.scrollIntoView({ behavior: "smooth" });
  });
});

// --- Sensibilidad del filtro de lenguaje ---
document.querySelectorAll(".btn-sensibilidad, .btn-sensibilidad-panel").forEach((btn) => {
  btn.addEventListener("click", () => cambiarSensibilidad(btn.dataset.nivel));
});

// --- Aviso global a estaciones ---
const modalAviso = document.getElementById("modalAviso");
const textoAviso = document.getElementById("textoAviso");
function abrirModalAviso() {
  modalAviso.classList.remove("oculto");
  textoAviso.value = "";
  textoAviso.focus();
}
document.getElementById("btnAlertaGlobal").addEventListener("click", abrirModalAviso);
document.getElementById("btnAlertaGlobal2").addEventListener("click", abrirModalAviso);
document.getElementById("btnCancelarAviso").addEventListener("click", () => modalAviso.classList.add("oculto"));
document.getElementById("btnEnviarAviso").addEventListener("click", async () => {
  const mensaje = textoAviso.value.trim();
  if (!mensaje) return;
  try {
    const resp = await apiFetch("/api/notificaciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensaje }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const datos = await resp.json();
    modalAviso.classList.add("oculto");
    mostrarToast(`Aviso enviado a ${datos.enviados} estación(es)`);
  } catch (err) {
    mostrarToast("No se pudo enviar el aviso: " + err.message);
  }
});

document.getElementById("btnVerificarServidor").addEventListener("click", async () => {
  try {
    const resp = await fetch("/api/salud");
    const datos = await resp.json();
    mostrarToast(resp.ok ? `Servidor OK — ${datos.app}` : "El servidor respondió con un error");
  } catch (err) {
    mostrarToast("No se pudo contactar al servidor: " + err.message);
  }
});

async function cargarCapacidadMaxima() {
  try {
    const resp = await fetch("/api/salud");
    const datos = await resp.json();
    window.__capacidadMaxima = datos.max_estaciones_concurrentes;
    renderizarKPIs();
  } catch (err) {
    // se queda mostrando el numero de conectadas como referencia
  }
}

// --- Opciones de sede/módulo (editables por el supervisor, ver Ley 1581 no aplica aqui,
// esto es solo config operativa que ve el select del empleado al iniciar sesion) ---
const opcionesSedeEl = document.getElementById("opcionesSede");
const opcionesModuloEl = document.getElementById("opcionesModulo");

async function cargarOpciones() {
  try {
    const resp = await fetch("/api/config/opciones"); // publico, no requiere token
    const datos = await resp.json();
    opcionesSedeEl.value = (datos.sede || []).join("\n");
    opcionesModuloEl.value = (datos.modulo || []).join("\n");
  } catch (err) {
    // el editor queda vacio; el empleado igual conserva lo que ya tenia sembrado en la BD
  }
}

document.getElementById("btnGuardarOpciones").addEventListener("click", async () => {
  const sedes = opcionesSedeEl.value.split("\n").map((s) => s.trim()).filter(Boolean);
  const modulos = opcionesModuloEl.value.split("\n").map((s) => s.trim()).filter(Boolean);
  try {
    await Promise.all([
      apiFetch("/api/config/opciones", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: "sede", valores: sedes }),
      }),
      apiFetch("/api/config/opciones", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: "modulo", valores: modulos }),
      }),
    ]);
    mostrarToast("Opciones de sede/módulo actualizadas");
  } catch (err) {
    mostrarToast("No se pudieron guardar las opciones: " + err.message);
  }
});

// --- Enlaces que necesitan el token (no pueden usar apiFetch porque son navegación directa) ---
function actualizarEnlacesConToken() {
  document.getElementById("linkInformeCsv").href = conToken("/api/informes/alertas.csv");
  document.getElementById("linkInformeCsvSidebar").href = conToken("/api/informes/alertas.csv");
}

// --- Sesión: login / logout ---
const pantallaLogin = document.getElementById("pantallaLogin");
const appContenido = document.getElementById("appContenido");
const formLogin = document.getElementById("formLogin");
const loginError = document.getElementById("loginError");

function iniciarPanel() {
  pantallaLogin.classList.add("oculto");
  appContenido.classList.remove("oculto");
  actualizarEnlacesConToken();
  cargarEstacionesActivas();
  cargarSensibilidad();
  cargarCapacidadMaxima();
  cargarOpciones();
  conectar();
}

formLogin.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  loginError.classList.add("oculto");
  const usuario = document.getElementById("loginUsuario").value.trim();
  const clave = document.getElementById("loginClave").value;
  try {
    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario, clave }),
    });
    if (!resp.ok) {
      const detalle = await resp.json().catch(() => ({}));
      throw new Error(detalle.detail || "No se pudo iniciar sesión");
    }
    const datos = await resp.json();
    tokenSesion = datos.token;
    sessionStorage.setItem(CLAVE_TOKEN, tokenSesion);
    iniciarPanel();
  } catch (err) {
    loginError.textContent = err.message;
    loginError.classList.remove("oculto");
  }
});

document.getElementById("btnCerrarSesion").addEventListener("click", async () => {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch (err) {
    // si el servidor no responde igual se cierra la sesion localmente
  }
  sessionStorage.removeItem(CLAVE_TOKEN);
  location.reload();
});

function cerrarSesionLocal(motivo) {
  sessionStorage.removeItem(CLAVE_TOKEN);
  tokenSesion = null;
  location.reload();
  if (motivo) console.warn(motivo);
}

if (tokenSesion) {
  iniciarPanel();
}
