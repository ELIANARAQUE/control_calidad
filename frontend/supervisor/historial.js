// Pagina "Historial y Reportes": el historial COMPLETO -una fila por sesion de monitoreo de
// todos los empleados, con hora de inicio, fin y sus alertas-, filtrable por fechas y/o por
// empleado, sede y/o modulo, con exportacion a Excel y PDF (de todo lo filtrado o solo de las
// filas marcadas). Las opciones de sede/modulo se administran en "Sedes y Módulos".

const tablaTrabajadoresEl = document.getElementById("tablaTrabajadores");
const vacioTrabajadoresEl = document.getElementById("vacioTrabajadores");
const contadorTrabajadoresEl = document.getElementById("contadorTrabajadores");
const textoPeriodoEl = document.getElementById("textoPeriodo");
const textoExportarEl = document.getElementById("textoExportar");
const filtroDesdeEl = document.getElementById("filtroDesde");
const filtroHastaEl = document.getElementById("filtroHasta");
const filtroPersonaEl = document.getElementById("filtroPersona");
const filtroSedeEl = document.getElementById("filtroSede");
const filtroModuloEl = document.getElementById("filtroModulo");
const errorFiltrosEl = document.getElementById("errorFiltros");
const seleccionarTodasEl = document.getElementById("seleccionarTodas");
const btnExportarExcel = document.getElementById("btnExportarExcel");
const btnExportarPdf = document.getElementById("btnExportarPdf");

let sesiones = []; // sesiones del periodo elegido (vienen del servidor)
const seleccionadas = new Set(); // ids de las sesiones marcadas
const expandidas = new Set(); // ids de las sesiones con el detalle de alertas abierto

const NOMBRE_TIPO = {
  lenguaje: "Lenguaje inapropiado",
  expresion: "Expresión negativa",
  ausencia: "Ausencia",
  expresion_positiva: "Expresión positiva",
  postura: "Postura",
};
const NOMBRE_PAUSA = { almuerzo: "Almuerzo", break: "Break" };
const NOMBRE_VEREDICTO = { confirmada: "Fue real", falsa_alarma: "Falsa alarma", sin_revisar: "Sin revisar" };

function fechaHora(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-CO", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function duracion(segundos) {
  const h = Math.floor(segundos / 3600), m = Math.floor((segundos % 3600) / 60), s = segundos % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min ${s} s` : `${s} s`;
}

function fechaCorta(yyyyMmDd) {
  const [a, m, d] = yyyyMmDd.split("-");
  return `${d}/${m}/${a}`;
}

function textoPeriodo() {
  const desde = filtroDesdeEl.value, hasta = filtroHastaEl.value;
  if (desde && hasta) return `Del ${fechaCorta(desde)} al ${fechaCorta(hasta)}`;
  if (desde) return `Desde el ${fechaCorta(desde)}`;
  if (hasta) return `Hasta el ${fechaCorta(hasta)}`;
  return "Todo el historial";
}

function consultaPeriodo() {
  const params = new URLSearchParams();
  if (filtroDesdeEl.value) params.set("desde", filtroDesdeEl.value);
  if (filtroHastaEl.value) params.set("hasta", filtroHastaEl.value);
  const texto = params.toString();
  return texto ? "?" + texto : "";
}

function filtradas() {
  const persona = filtroPersonaEl.value, sede = filtroSedeEl.value, modulo = filtroModuloEl.value;
  return sesiones.filter(
    (s) => (!persona || s.nombre === persona) && (!sede || s.sede === sede) && (!modulo || s.modulo === modulo)
  );
}

// Opciones del filtro: TODAS las configuradas en la base de datos (tabla opciones_configurables)
// mas las que aparecen en sesiones viejas y ya se renombraron o eliminaron.
let opcionesConfiguradas = { sede: [], modulo: [] };

async function cargarOpcionesFiltro() {
  try {
    const resp = await fetch("/api/config/opciones");
    if (resp.ok) opcionesConfiguradas = await resp.json();
  } catch (err) {
    // sin conexion: quedan solo las que aparecen en las sesiones
  }
  pintarFiltrosSedeModulo();
}

function pintarFiltrosSedeModulo() {
  llenarSelect(filtroSedeEl, [...(opcionesConfiguradas.sede || []), ...sesiones.map((s) => s.sede)], "Todas las sedes");
  llenarSelect(filtroModuloEl, [...(opcionesConfiguradas.modulo || []), ...sesiones.map((s) => s.modulo)], "Todos los módulos");
}
function llenarSelect(select, valores, textoTodos) {
  const actual = select.value;
  const unicos = [...new Set(valores.filter(Boolean))].sort((a, b) => a.localeCompare(b, "es"));
  select.innerHTML =
    `<option value="">${textoTodos}</option>` +
    unicos.map((v) => `<option value="${escaparHtml(v)}">${escaparHtml(v)}</option>`).join("");
  select.value = unicos.includes(actual) ? actual : "";
}

function textoFiltrosActivos() {
  return [
    filtroPersonaEl.value || "todos los empleados",
    filtroSedeEl.value && `sede ${filtroSedeEl.value}`,
    filtroModuloEl.value && `módulo ${filtroModuloEl.value}`,
  ].filter(Boolean).join(" · ");
}

// Lo que se exporta: las filas marcadas (si hay alguna visible marcada) o todo lo filtrado.
function filasAExportar() {
  const visibles = filtradas();
  const marcadas = visibles.filter((s) => seleccionadas.has(s.id));
  return marcadas.length ? marcadas : visibles;
}

function actualizarControlesExportar() {
  const visibles = filtradas();
  const marcadas = visibles.filter((s) => seleccionadas.has(s.id)).length;
  textoExportarEl.textContent = marcadas
    ? `Exportar ${marcadas} fila${marcadas === 1 ? "" : "s"} seleccionada${marcadas === 1 ? "" : "s"}:`
    : "Exportar todo lo filtrado:";
  btnExportarExcel.disabled = btnExportarPdf.disabled = visibles.length === 0;
  seleccionarTodasEl.checked = visibles.length > 0 && marcadas === visibles.length;
  seleccionarTodasEl.indeterminate = marcadas > 0 && marcadas < visibles.length;
}

function resumenAlertas(s) {
  const partes = [
    [s.alertas_lenguaje, "lenguaje"],
    [s.alertas_expresion, "expresión"],
    [s.alertas_ausencia, "ausencia"],
  ].filter(([n]) => n > 0).map(([n, t]) => `${n} ${t}`);
  if (s.expresiones_positivas) partes.push(`${s.expresiones_positivas} positiva${s.expresiones_positivas === 1 ? "" : "s"}`);
  return partes.join(" · ");
}

// "Almuerzo 55 min (1) · Break 20 min (4)": tiempo TOTAL de cada tipo en la sesion.
function resumenPausas(s) {
  const partes = [];
  if (s.veces_almuerzo) partes.push(`<span title="${s.veces_almuerzo} vez/veces">🍽 ${duracion(s.segundos_almuerzo)} <span class="text-on-surface-variant">(${s.veces_almuerzo})</span></span>`);
  if (s.veces_break) partes.push(`<span title="${s.veces_break} vez/veces">☕ ${duracion(s.segundos_break)} <span class="text-on-surface-variant">(${s.veces_break})</span></span>`);
  return partes.length ? partes.join("<br>") : '<span class="text-on-surface-variant">—</span>';
}

function filaPausas(s) {
  if (!s.pausas?.length) return "";
  const filas = s.pausas.map((p) => `
      <tr class="border-b border-outline-variant last:border-0">
        <td class="py-1 pr-space-sm whitespace-nowrap font-semibold">${NOMBRE_PAUSA[p.tipo] || escaparHtml(p.tipo)}</td>
        <td class="py-1 pr-space-sm whitespace-nowrap">${fechaHora(p.inicio)}</td>
        <td class="py-1 pr-space-sm whitespace-nowrap">${p.fin ? fechaHora(p.fin) : "En curso"}</td>
        <td class="py-1 whitespace-nowrap">${duracion(p.segundos)}</td>
      </tr>`).join("");
  return `
    <p class="font-label-md text-label-md text-on-surface font-bold mt-space-sm mb-1">Almuerzos y breaks · tiempo efectivo de la sesión: ${duracion(s.segundos_efectivos)}</p>
    <table class="w-full text-left font-body-sm text-body-sm text-on-surface">
      <thead><tr class="text-on-surface-variant font-label-sm text-label-sm uppercase">
        <th class="pb-1 pr-space-sm">Tipo</th><th class="pb-1 pr-space-sm">Salida</th><th class="pb-1 pr-space-sm">Regreso</th><th class="pb-1">Duración</th>
      </tr></thead>
      <tbody>${filas}</tbody>
    </table>`;
}

function filaDetalle(s) {
  const filas = s.alertas.length
    ? s.alertas.map((a) => `
        <tr class="border-b border-outline-variant last:border-0">
          <td class="py-1 pr-space-sm whitespace-nowrap">${fechaHora(a.timestamp)}</td>
          <td class="py-1 pr-space-sm whitespace-nowrap font-semibold">${NOMBRE_TIPO[a.tipo] || escaparHtml(a.tipo)}</td>
          <td class="py-1 pr-space-sm">${escaparHtml(a.detalle || "")}</td>
          <td class="py-1 whitespace-nowrap">${a.tipo === "expresion_positiva" ? "—" : NOMBRE_VEREDICTO[a.veredicto] || escaparHtml(a.veredicto)}</td>
        </tr>`).join("")
    : '<tr><td class="py-1 text-on-surface-variant" colspan="4">Sin alertas en esta sesión.</td></tr>';
  return `
    <tr class="bg-surface-container-low">
      <td></td>
      <td class="py-space-sm pr-space-sm" colspan="9">
        <table class="w-full text-left font-body-sm text-body-sm text-on-surface">
          <thead><tr class="text-on-surface-variant font-label-sm text-label-sm uppercase">
            <th class="pb-1 pr-space-sm">Fecha y hora</th><th class="pb-1 pr-space-sm">Tipo</th><th class="pb-1 pr-space-sm">Detalle</th><th class="pb-1">Veredicto</th>
          </tr></thead>
          <tbody>${filas}</tbody>
        </table>
        ${filaPausas(s)}
      </td>
    </tr>`;
}

function renderizarTabla() {
  const lista = filtradas();
  const consulta = consultaPeriodo();

  contadorTrabajadoresEl.textContent = `${lista.length} sesi${lista.length === 1 ? "ón" : "ones"}`;
  textoPeriodoEl.textContent = `${textoPeriodo()} · ${textoFiltrosActivos()}`;
  vacioTrabajadoresEl.classList.toggle("oculto", lista.length > 0);

  tablaTrabajadoresEl.innerHTML = lista
    .map((s) => {
      const abierta = expandidas.has(s.id);
      const alertas = s.total_alertas > 0
        ? `<span class="font-semibold text-error">${s.total_alertas}</span>`
        : `<span class="text-on-surface-variant">0</span>`;
      const resumen = resumenAlertas(s);
      const url = `/api/informes/trabajadores/${encodeURIComponent(s.nombre)}/reporte.xlsx${consulta}`;
      return `
        <tr class="border-b border-surface-container-low hover:bg-surface-container-low transition-colors" data-id="${escaparHtml(s.id)}">
          <td class="py-space-sm pr-space-sm">
            <input class="check-fila" type="checkbox" ${seleccionadas.has(s.id) ? "checked" : ""} aria-label="Seleccionar sesión de ${escaparHtml(s.nombre)}" />
          </td>
          <td class="py-space-sm pr-space-sm">
            <div class="flex items-center gap-2">
              <div class="avatar-estacion" style="background:${Core.colorAvatar(s.nombre)}">${Core.iniciales(s.nombre)}</div>
              <span class="font-body-md text-body-md font-semibold text-on-surface">${escaparHtml(s.nombre)}</span>
            </div>
          </td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface-variant">${escaparHtml(s.sede || "—")}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface-variant">${escaparHtml(s.modulo || "—")}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface whitespace-nowrap">${fechaHora(s.inicio)}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm whitespace-nowrap">${s.fin ? fechaHora(s.fin) : '<span class="font-semibold text-[#10b981]">En curso</span>'}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm text-on-surface-variant whitespace-nowrap">${duracion(s.duracion_segundos)}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm whitespace-nowrap">${resumenPausas(s)}</td>
          <td class="py-space-sm pr-space-sm font-body-sm text-body-sm">
            <button class="btn-detalle flex flex-col items-start text-left min-w-[120px]" type="button" title="Ver el detalle de las alertas">
              <span class="flex items-center gap-1">${alertas}<span class="text-primary font-semibold">${abierta ? "Ocultar" : "Ver detalle"}</span>
                <span class="material-symbols-outlined text-[18px] text-primary">${abierta ? "expand_less" : "expand_more"}</span></span>
              <span class="text-on-surface-variant text-[11px] leading-tight">${resumen}</span>
            </button>
          </td>
          <td class="py-space-sm">
            <a class="flex items-center gap-1 px-space-sm py-1 rounded-lg bg-primary text-white font-label-sm text-label-sm font-semibold hover:opacity-90 transition-opacity w-max" href="${Core.conToken(url)}" title="Reporte individual de ${escaparHtml(s.nombre)} (.xlsx) en el periodo filtrado">
              <span class="material-symbols-outlined text-[16px]">download</span><span>Reporte</span>
            </a>
          </td>
        </tr>
        ${abierta ? filaDetalle(s) : ""}
      `;
    })
    .join("");
  actualizarControlesExportar();
}

// La lista de empleados del filtro sale de todo el historial (no solo del periodo), para poder
// elegir a alguien aunque todavia no se hayan puesto fechas.
async function cargarPersonas() {
  try {
    const resp = await Core.apiFetch("/api/informes/trabajadores");
    if (!resp.ok) return;
    const nombres = (await resp.json()).map((t) => t.nombre).sort((a, b) => a.localeCompare(b, "es"));
    const actual = filtroPersonaEl.value;
    filtroPersonaEl.innerHTML =
      '<option value="">Todos los empleados</option>' +
      nombres.map((n) => `<option value="${escaparHtml(n)}">${escaparHtml(n)}</option>`).join("");
    filtroPersonaEl.value = nombres.includes(actual) ? actual : "";
  } catch (err) {
    // sin la lista, el filtro por empleado queda solo con "Todos los empleados"
  }
}

async function cargarSesiones() {
  const desde = filtroDesdeEl.value, hasta = filtroHastaEl.value;
  if (desde && hasta && desde > hasta) {
    errorFiltrosEl.textContent = "La fecha 'Desde' no puede ser posterior a la fecha 'Hasta'.";
    errorFiltrosEl.classList.remove("oculto");
    return;
  }
  errorFiltrosEl.classList.add("oculto");
  try {
    const resp = await Core.apiFetch("/api/informes/sesiones" + consultaPeriodo());
    if (!resp.ok) throw new Error(await detalleError(resp));
    sesiones = await resp.json();
    pintarFiltrosSedeModulo();
    renderizarTabla();
  } catch (err) {
    Core.mostrarToast("No se pudo cargar el historial: " + err.message);
  }
}

filtroDesdeEl.addEventListener("change", cargarSesiones);
filtroHastaEl.addEventListener("change", cargarSesiones);
filtroPersonaEl.addEventListener("change", renderizarTabla);
filtroSedeEl.addEventListener("change", renderizarTabla);
filtroModuloEl.addEventListener("change", renderizarTabla);
document.getElementById("btnLimpiarFiltros").addEventListener("click", () => {
  filtroDesdeEl.value = "";
  filtroHastaEl.value = "";
  filtroPersonaEl.value = "";
  filtroSedeEl.value = "";
  filtroModuloEl.value = "";
  seleccionadas.clear();
  cargarSesiones();
});

tablaTrabajadoresEl.addEventListener("change", (ev) => {
  const check = ev.target.closest(".check-fila");
  if (!check) return;
  const id = check.closest("tr").dataset.id;
  if (check.checked) seleccionadas.add(id);
  else seleccionadas.delete(id);
  actualizarControlesExportar();
});

tablaTrabajadoresEl.addEventListener("click", (ev) => {
  const boton = ev.target.closest(".btn-detalle");
  if (!boton) return;
  const id = boton.closest("tr").dataset.id;
  if (expandidas.has(id)) expandidas.delete(id);
  else expandidas.add(id);
  renderizarTabla();
});

seleccionarTodasEl.addEventListener("change", () => {
  for (const s of filtradas()) {
    if (seleccionarTodasEl.checked) seleccionadas.add(s.id);
    else seleccionadas.delete(s.id);
  }
  renderizarTabla();
});

// --- Exportacion (Excel con SheetJS, PDF con jsPDF + autoTable) ---
// Hoja/tabla 1: una fila por sesion. Hoja/tabla 2: cada alerta de esas sesiones.
const COLUMNAS_SESIONES = [
  ["Empleado", (s) => s.nombre],
  ["Sede", (s) => s.sede || "—"],
  ["Módulo", (s) => s.modulo || "—"],
  ["Inicio de sesión", (s) => fechaHora(s.inicio)],
  ["Fin de sesión", (s) => (s.fin ? fechaHora(s.fin) : "En curso")],
  ["Duración", (s) => duracion(s.duracion_segundos)],
  ["Almuerzo", (s) => (s.veces_almuerzo ? `${duracion(s.segundos_almuerzo)} (${s.veces_almuerzo})` : "—")],
  ["Break", (s) => (s.veces_break ? `${duracion(s.segundos_break)} (${s.veces_break})` : "—")],
  ["Tiempo efectivo", (s) => duracion(s.segundos_efectivos)],
  ["Alertas lenguaje", (s) => s.alertas_lenguaje],
  ["Alertas expresión", (s) => s.alertas_expresion],
  ["Alertas ausencia", (s) => s.alertas_ausencia],
  ["Total alertas", (s) => s.total_alertas],
  ["Expresiones positivas", (s) => s.expresiones_positivas],
];
const COLUMNAS_ALERTAS = ["Empleado", "Sede", "Módulo", "Fecha y hora", "Tipo", "Detalle", "Veredicto"];

function filasAlertas(lista) {
  return lista.flatMap((s) =>
    s.alertas.map((a) => [
      s.nombre,
      s.sede || "—",
      s.modulo || "—",
      fechaHora(a.timestamp),
      NOMBRE_TIPO[a.tipo] || a.tipo,
      a.detalle || "",
      a.tipo === "expresion_positiva" ? "—" : NOMBRE_VEREDICTO[a.veredicto] || a.veredicto,
    ])
  );
}

function nombreArchivo(extension) {
  const hoy = new Date().toISOString().slice(0, 10);
  const partes = [filtroPersonaEl.value, filtroSedeEl.value, filtroModuloEl.value]
    .filter(Boolean)
    .map((v) => "_" + v.replace(/[^\p{L}\p{N}]+/gu, "_"))
    .join("");
  return `historial_sesiones${partes}_${hoy}.${extension}`;
}

function descripcionFiltros(filas) {
  const persona = filtroPersonaEl.value || "Todos los empleados";
  const sede = filtroSedeEl.value || "Todas";
  const modulo = filtroModuloEl.value || "Todos";
  const marcadas = filtradas().some((s) => seleccionadas.has(s.id));
  return `Periodo: ${textoPeriodo()} · Empleado: ${persona} · Sede: ${sede} · Módulo: ${modulo} · ${marcadas ? "Filas seleccionadas" : "Todo lo filtrado"} (${filas.length} sesi${filas.length === 1 ? "ón" : "ones"})`;
}

// El Excel lo arma el servidor con la plantilla completa y desglosada: hojas Resumen, Sesiones,
// Alertas (con la foto de cada una) y Transcripciones, de las sesiones filtradas o marcadas.
btnExportarExcel.addEventListener("click", async () => {
  const filas = filasAExportar();
  const textoOriginal = btnExportarExcel.innerHTML;
  btnExportarExcel.disabled = true;
  btnExportarExcel.innerHTML = '<span class="material-symbols-outlined text-[18px] animate-spin">progress_activity</span>Generando…';
  try {
    const resp = await Core.apiFetch("/api/informes/sesiones/reporte.xlsx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        desde: filtroDesdeEl.value || null,
        hasta: filtroHastaEl.value || null,
        ids: filas.map((s) => s.id),
        descripcion: descripcionFiltros(filas),
      }),
    });
    if (!resp.ok) throw new Error(await detalleError(resp));
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(await resp.blob());
    enlace.download = nombreArchivo("xlsx");
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(enlace.href), 10000);
  } catch (err) {
    Core.mostrarToast("No se pudo generar el Excel: " + err.message);
  } finally {
    btnExportarExcel.innerHTML = textoOriginal;
    actualizarControlesExportar();
  }
});

btnExportarPdf.addEventListener("click", () => {
  if (!window.jspdf) return Core.mostrarToast("No se pudo cargar la librería de PDF (revisa la conexión a internet)");
  const filas = filasAExportar();
  const doc = new window.jspdf.jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  const estilos = {
    styles: { fontSize: 7.5, cellPadding: 3.5 },
    headStyles: { fillColor: [91, 70, 214], textColor: 255 },
    alternateRowStyles: { fillColor: [243, 238, 251] },
    margin: { left: 36, right: 36 },
  };
  doc.setFontSize(15);
  doc.setTextColor(43, 33, 86);
  doc.text("Historial de sesiones — Control de Calidad", 36, 40);
  doc.setFontSize(9);
  doc.setTextColor(107, 100, 133);
  doc.text("Universitaria de Colombia", 36, 56);
  doc.text(descripcionFiltros(filas), 36, 70);
  doc.text(`Generado el ${new Date().toLocaleString("es-CO")}`, 36, 84);
  doc.autoTable({
    ...estilos,
    startY: 96,
    head: [COLUMNAS_SESIONES.map(([titulo]) => titulo)],
    body: filas.map((s) => COLUMNAS_SESIONES.map(([, valor]) => String(valor(s)))),
  });
  const alertas = filasAlertas(filas);
  doc.setFontSize(11);
  doc.setTextColor(43, 33, 86);
  let y = doc.lastAutoTable.finalY + 26;
  if (y > doc.internal.pageSize.getHeight() - 60) {
    doc.addPage();
    y = 40;
  }
  const pausas = filas.flatMap((s) =>
    (s.pausas || []).map((p) => [s.nombre, s.sede || "—", s.modulo || "—", NOMBRE_PAUSA[p.tipo] || p.tipo, fechaHora(p.inicio), p.fin ? fechaHora(p.fin) : "En curso", duracion(p.segundos)])
  );
  doc.text("Almuerzos y breaks", 36, y);
  doc.autoTable({
    ...estilos,
    startY: y + 8,
    head: [["Empleado", "Sede", "Módulo", "Tipo", "Salida", "Regreso", "Duración"]],
    body: pausas.length ? pausas : [["Sin almuerzos ni breaks en las sesiones exportadas.", "", "", "", "", "", ""]],
  });
  y = doc.lastAutoTable.finalY + 26;
  if (y > doc.internal.pageSize.getHeight() - 60) {
    doc.addPage();
    y = 40;
  }
  doc.setFontSize(11);
  doc.setTextColor(43, 33, 86);
  doc.text("Detalle de alertas", 36, y);
  doc.autoTable({
    ...estilos,
    startY: y + 8,
    head: [COLUMNAS_ALERTAS],
    body: alertas.length ? alertas : [["Sin alertas en las sesiones exportadas.", "", "", "", "", "", ""]],
    columnStyles: { 5: { cellWidth: 260 } },
  });
  doc.save(nombreArchivo("pdf"));
});

// --- Utilidades ---
function escaparHtml(texto) {
  return texto.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function detalleError(resp) {
  const cuerpo = await resp.json().catch(() => ({}));
  return typeof cuerpo.detail === "string" ? cuerpo.detail : "HTTP " + resp.status;
}

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
  cargarPersonas();
  cargarOpcionesFiltro();
  cargarSesiones();
});
