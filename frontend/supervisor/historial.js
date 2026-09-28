// Pagina "Historial y Reportes": lista de trabajadores con boton para descargar su reporte
// de evaluacion individual (.xlsx), y el editor de opciones de sede/modulo.

const tablaTrabajadoresEl = document.getElementById("tablaTrabajadores");
const vacioTrabajadoresEl = document.getElementById("vacioTrabajadores");
const contadorTrabajadoresEl = document.getElementById("contadorTrabajadores");
const buscadorEl = document.getElementById("buscador");

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

// --- CRUD de opciones de Sede / Módulo (una fila por opcion: editar, eliminar, añadir) ---
function escaparHtml(texto) {
  return texto.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function detalleError(resp) {
  const cuerpo = await resp.json().catch(() => ({}));
  return typeof cuerpo.detail === "string" ? cuerpo.detail : "HTTP " + resp.status;
}

function filaLectura(opcion) {
  return `<tr class="border-b border-outline-variant" data-id="${opcion.id}">
    <td class="py-space-xs pr-space-sm">${escaparHtml(opcion.valor)}</td>
    <td class="py-space-xs text-right whitespace-nowrap">
      <button class="btn-veredicto" data-accion="editar" type="button"><span class="material-symbols-outlined text-[14px] align-middle">edit</span> Editar</button>
      <button class="btn-veredicto btn-eliminar" data-accion="eliminar" type="button"><span class="material-symbols-outlined text-[14px] align-middle">delete</span> Eliminar</button>
    </td>
  </tr>`;
}

function filaEdicion(opcion) {
  return `<tr class="border-b border-outline-variant" data-id="${opcion.id}">
    <td class="py-space-xs pr-space-sm">
      <input class="w-full bg-surface-container-low border border-primary rounded-lg px-space-sm py-1 focus:outline-none" maxlength="80" value="${escaparHtml(opcion.valor)}" />
    </td>
    <td class="py-space-xs text-right whitespace-nowrap">
      <button class="btn-veredicto btn-descartar" data-accion="guardar" type="button">Guardar</button>
      <button class="btn-veredicto" data-accion="cancelar" type="button">Cancelar</button>
    </td>
  </tr>`;
}

let opciones = [];

function pintarOpciones() {
  document.querySelectorAll(".crud-opciones").forEach((panel) => {
    const lista = opciones.filter((o) => o.tipo === panel.dataset.tipo);
    panel.querySelector("tbody").innerHTML = lista.length
      ? lista.map(filaLectura).join("")
      : '<tr><td colspan="2" class="py-space-sm text-on-surface-variant">Sin opciones: el empleado no podrá elegir. Añade al menos una.</td></tr>';
  });
}

async function cargarOpciones() {
  try {
    const resp = await Core.apiFetch("/api/config/opciones/detalle");
    if (!resp.ok) throw new Error(await detalleError(resp));
    opciones = await resp.json();
    pintarOpciones();
  } catch (err) {
    Core.mostrarToast("No se pudieron cargar las opciones: " + err.message);
  }
}

document.querySelectorAll(".crud-opciones").forEach((panel) => {
  const tipo = panel.dataset.tipo;

  panel.querySelector(".form-nueva-opcion").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = ev.target.querySelector("input");
    const resp = await Core.apiFetch("/api/config/opciones/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tipo, valor: input.value }),
    });
    if (!resp.ok) return Core.mostrarToast("No se pudo añadir: " + (await detalleError(resp)));
    input.value = "";
    Core.mostrarToast("Opción añadida");
    cargarOpciones();
  });

  panel.querySelector("tbody").addEventListener("click", async (ev) => {
    const boton = ev.target.closest("button[data-accion]");
    if (!boton) return;
    const fila = boton.closest("tr");
    const opcion = opciones.find((o) => String(o.id) === fila.dataset.id);
    if (!opcion) return;

    if (boton.dataset.accion === "editar") {
      fila.outerHTML = filaEdicion(opcion);
      panel.querySelector(`tr[data-id="${opcion.id}"] input`).focus();
    } else if (boton.dataset.accion === "cancelar") {
      pintarOpciones();
    } else if (boton.dataset.accion === "guardar") {
      const valor = fila.querySelector("input").value;
      const resp = await Core.apiFetch(`/api/config/opciones/items/${opcion.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valor }),
      });
      if (!resp.ok) return Core.mostrarToast("No se pudo guardar: " + (await detalleError(resp)));
      Core.mostrarToast("Opción actualizada (solo afecta a las sesiones nuevas)");
      cargarOpciones();
    } else if (boton.dataset.accion === "eliminar") {
      if (!confirm(`¿Eliminar "${opcion.valor}"? Las sesiones ya registradas con esta opción no se modifican.`)) return;
      const resp = await Core.apiFetch(`/api/config/opciones/items/${opcion.id}`, { method: "DELETE" });
      if (!resp.ok) return Core.mostrarToast("No se pudo eliminar: " + (await detalleError(resp)));
      Core.mostrarToast("Opción eliminada");
      cargarOpciones();
    }
  });
});

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
});
