// Pagina "Transcripciones": todas las frases transcritas por Whisper, de todas las
// estaciones, mas recientes primero.

const feedEl = document.getElementById("feed");
const contadorTranscripcionesEl = document.getElementById("contadorTranscripciones");
const buscadorEl = document.getElementById("buscador");
let filtroBusqueda = "";

function renderizar() {
  const combinado = [];
  for (const [id, datos] of Core.estaciones) {
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
