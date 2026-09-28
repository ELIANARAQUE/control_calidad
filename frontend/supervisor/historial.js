// Pagina "Historial y Reportes": lista de trabajadores con boton para descargar su reporte
// de evaluacion individual (.xlsx), y el editor de opciones de sede/modulo.

const tablaTrabajadoresEl = document.getElementById("tablaTrabajadores");
const vacioTrabajadoresEl = document.getElementById("vacioTrabajadores");
const contadorTrabajadoresEl = document.getElementById("contadorTrabajadores");
const buscadorEl = document.getElementById("buscador");
const opcionesSedeEl = document.getElementById("opcionesSede");
const opcionesModuloEl = document.getElementById("opcionesModulo");

let trabajadores = [];
let filtroBusqueda = "";

function fechaLegible(iso) {
  if (!iso) return "—";
  const dt = new Date(iso);
  return dt.toLocaleString("es-CO", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function renderizarTabla() {
  const filtrados = filtroBusqueda
    ? trabajadores.filter((t) => t.nombre.toLowerCase().includes(filtroBusqueda))
    : trabajadores;

  contadorTrabajadoresEl.textContent = `${trabajadores.length} trabajador${trabajadores.length === 1 ? "" : "es"}`;
  vacioTrabajadoresEl.classList.toggle("oculto", filtrados.length > 0);

  tablaTrabajadoresEl.innerHTML = filtrados
    .map((t) => {
      const sedeModulo = [...t.sedes, ...t.modulos].join(" · ") || "—";
      const alertasTexto = t.total_alertas > 0
        ? `<span class="font-semibold text-error">${t.total_alertas}</span>`
        : `<span class="text-on-surface-variant">0</span>`;
      return `
        <tr class="border-b border-surface-container-low hover:bg-surface-container-low transition-colors">
          <td class="py-space-sm pr-space-sm">
            <div class="flex items-center gap-2">
              <div class="avatar-estacion" style="background:${Core.colorAvatar(t.nombre)}">${Core.iniciales(t.nombre)}</div>
              <span class="font-body-md text-body-md font-semibold text-on-surface">${t.nombre}</span>
            </div>
          </td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface-variant">${sedeModulo}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface">${t.sesiones}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm">${alertasTexto}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface-variant">${fechaLegible(t.ultima_conexion)}</td>
          <td class="py-space-sm">
            <a class="flex items-center gap-1 px-space-sm py-1 rounded-lg bg-primary text-white font-label-sm text-label-sm font-semibold hover:opacity-90 transition-opacity w-max" href="${Core.conToken(`/api/informes/trabajadores/${encodeURIComponent(t.nombre)}/reporte.xlsx`)}">
              <span class="material-symbols-outlined text-[16px]">download</span><span>Descargar reporte</span>
            </a>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function cargarTrabajadores() {
  try {
    const resp = await Core.apiFetch("/api/informes/trabajadores");
    if (!resp.ok) return;
    trabajadores = await resp.json();
    renderizarTabla();
  } catch (err) {
    Core.mostrarToast("No se pudo cargar la lista de trabajadores: " + err.message);
  }
}

buscadorEl.addEventListener("input", () => {
  filtroBusqueda = buscadorEl.value.trim().toLowerCase();
  renderizarTabla();
});

async function cargarOpciones() {
  try {
    const resp = await fetch("/api/config/opciones"); // publico
    const datos = await resp.json();
    opcionesSedeEl.value = (datos.sede || []).join("\n");
    opcionesModuloEl.value = (datos.modulo || []).join("\n");
  } catch (err) {
    // el editor queda vacio
  }
}

document.getElementById("btnGuardarOpciones").addEventListener("click", async () => {
  const sedes = opcionesSedeEl.value.split("\n").map((s) => s.trim()).filter(Boolean);
  const modulos = opcionesModuloEl.value.split("\n").map((s) => s.trim()).filter(Boolean);
  try {
    await Promise.all([
      Core.apiFetch("/api/config/opciones", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: "sede", valores: sedes }),
      }),
      Core.apiFetch("/api/config/opciones", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: "modulo", valores: modulos }),
      }),
    ]);
    Core.mostrarToast("Opciones de sede/módulo actualizadas");
  } catch (err) {
    Core.mostrarToast("No se pudieron guardar las opciones: " + err.message);
  }
});

// La lista de trabajadores no necesita re-renderizarse en cada evento en vivo (es historico,
// no telemetria); solo se recarga al abrir la pagina. El badge de pendientes en la topbar
// (compartido) si sigue actualizandose via Core.onEvento internamente.
// --- Diccionario de lenguaje inapropiado (tabla `lenguaje_inapropiado` en Supabase) ---
const CAMPOS_LENGUAJE = {
  groseria_fuerte: document.getElementById("lenguajeFuerte"),
  groseria_leve: document.getElementById("lenguajeLeve"),
  mal_trato: document.getElementById("lenguajeMalTrato"),
};

function pintarLenguaje(datos) {
  for (const [categoria, campo] of Object.entries(CAMPOS_LENGUAJE)) {
    campo.value = (datos[categoria] || []).join("\n");
  }
}

async function cargarLenguaje() {
  try {
    const resp = await Core.apiFetch("/api/config/lenguaje");
    if (resp.ok) pintarLenguaje(await resp.json());
  } catch (err) {
    Core.mostrarToast("No se pudo cargar el diccionario de lenguaje: " + err.message);
  }
}

document.getElementById("btnGuardarLenguaje").addEventListener("click", async () => {
  try {
    let ultimo = null;
    for (const [categoria, campo] of Object.entries(CAMPOS_LENGUAJE)) {
      const terminos = campo.value.split("\n").map((t) => t.trim()).filter(Boolean);
      const resp = await Core.apiFetch("/api/config/lenguaje", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categoria, terminos }),
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      ultimo = await resp.json();
    }
    if (ultimo) pintarLenguaje(ultimo);
    Core.mostrarToast("Diccionario de lenguaje actualizado");
  } catch (err) {
    Core.mostrarToast("No se pudo guardar el diccionario: " + err.message);
  }
});

Core.iniciar(() => {
  cargarTrabajadores();
  cargarOpciones();
  cargarLenguaje();
});
