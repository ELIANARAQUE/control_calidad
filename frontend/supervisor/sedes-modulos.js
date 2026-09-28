// Pagina "Sedes y Módulos": CRUD de las opciones que el empleado elige al iniciar su monitoreo
// (una fila por opcion: editar, eliminar, añadir). Editar o eliminar solo afecta a las sesiones
// nuevas: las ya registradas conservan el nombre con el que se guardaron.

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

Core.iniciar(() => {
  cargarOpciones();
});
