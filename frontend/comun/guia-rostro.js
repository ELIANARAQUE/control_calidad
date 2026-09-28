// Guia de captura de rostro (registro y login): dibuja un ovalo sobre la camara y SOLO deja
// tomar la foto cuando la cara esta dentro del ovalo, al tamaño correcto y en el angulo
// pedido (de frente, perfil izquierdo o perfil derecho). Usa el mismo modelo de MediaPipe
// Face Landmarker que el script de referencia de "Deteccion de Rostro", pero corriendo en el
// navegador para dar la retroalimentacion en vivo.
//
// El servidor vuelve a validar el angulo al registrar (ver app/core/cuentas.py): esta guia es
// la experiencia de usuario, no la unica barrera.

const VERSION_MEDIAPIPE = "0.10.14";
const URL_LIBRERIA = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION_MEDIAPIPE}/vision_bundle.mjs`;
const URL_WASM = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION_MEDIAPIPE}/wasm`;
const URL_MODELO = "/comun/modelos/face_landmarker.task";

// Ovalo guia, en coordenadas normalizadas del video (0..1).
const OVALO = { cx: 0.5, cy: 0.5, rx: 0.24, ry: 0.4 };
const CUADROS_ESTABLES = 6; // cuadros seguidos validos antes de habilitar la foto

// Puntos de la malla facial de MediaPipe usados para estimar el giro de la cabeza.
const PUNTA_NARIZ = 1;
const MEJILLA_IMAGEN_IZQ = 234; // borde de la cara del lado izquierdo de la imagen
const MEJILLA_IMAGEN_DER = 454; // borde de la cara del lado derecho de la imagen
const FRENTE = 10;
const MENTON = 152;

export const INSTRUCCIONES = {
  frontal: "Mira de frente a la cámara, con tu rostro dentro del óvalo.",
  izquierda: "Gira la cabeza hacia TU IZQUIERDA en tres cuartos (unos 45°), sin llegar a perfil completo.",
  derecha: "Gira la cabeza hacia TU DERECHA en tres cuartos (unos 45°), sin llegar a perfil completo.",
};

let promesaLibreria = null;
function cargarLibreria() {
  promesaLibreria ??= import(URL_LIBRERIA);
  return promesaLibreria;
}

async function crearLandmarker(modo) {
  const { FaceLandmarker, FilesetResolver } = await cargarLibreria();
  const archivos = await FilesetResolver.forVisionTasks(URL_WASM);
  return FaceLandmarker.createFromOptions(archivos, {
    baseOptions: { modelAssetPath: URL_MODELO },
    runningMode: modo,
    numFaces: 2, // se piden 2 solo para poder avisar "hay mas de una persona"
  });
}

// Evalua UNA deteccion contra el angulo pedido. Devuelve { valido, mensaje }.
// `encuadre=false` (fotos subidas): se omiten las reglas de tamaño/centrado respecto al ovalo.
export function evaluarRostro(caras, angulo, { encuadre = true } = {}) {
  if (!caras || caras.length === 0) {
    // Un perfil completo (90°) ya no se detecta como cara: en las fotos laterales, lo mas
    // probable es que la persona haya girado de mas.
    return {
      valido: false,
      mensaje:
        angulo === "frontal"
          ? "No se detecta ningún rostro. Ubícate frente a la cámara."
          : "No se detecta tu rostro: gira un poco MENOS la cabeza (tres cuartos, no perfil completo).",
    };
  }
  if (caras.length > 1) return { valido: false, mensaje: "Hay más de una persona en la imagen: debe aparecer solo una." };

  const p = caras[0];
  const xs = p.map((l) => l.x);
  const ys = p.map((l) => l.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, alto = maxY - minY;

  if (encuadre) {
    // Tamaño: la cara debe llenar el ovalo de forma razonable (ni muy lejos ni muy cerca).
    const altoOvalo = OVALO.ry * 2;
    if (alto < altoOvalo * 0.5) return { valido: false, mensaje: "Acércate un poco más a la cámara." };
    if (alto > altoOvalo * 1.08) return { valido: false, mensaje: "Aléjate un poco de la cámara." };

    // Posicion: el centro de la cara debe estar cerca del centro del ovalo.
    const dx = (cx - OVALO.cx) / OVALO.rx, dy = (cy - OVALO.cy) / OVALO.ry;
    if (dx * dx + dy * dy > 0.25) return { valido: false, mensaje: "Centra tu rostro dentro del óvalo." };
  } else if (alto < 0.2) {
    return { valido: false, mensaje: "El rostro se ve muy pequeño en la foto: usa una foto más cercana." };
  }

  // Inclinacion vertical: ni mirando muy arriba ni muy abajo.
  const vertical = (p[PUNTA_NARIZ].y - p[FRENTE].y) / (p[MENTON].y - p[FRENTE].y);
  if (vertical < 0.38) return { valido: false, mensaje: "Baja un poco la barbilla." };
  if (vertical > 0.72) return { valido: false, mensaje: "Levanta un poco la barbilla." };

  // Giro horizontal: posicion de la nariz entre los dos bordes de la cara (0.5 = de frente).
  // Con la camara sin espejo, cuando la persona gira hacia SU izquierda la nariz se corre
  // hacia el lado derecho de la imagen (el valor sube); hacia su derecha, baja.
  const izq = p[MEJILLA_IMAGEN_IZQ].x, der = p[MEJILLA_IMAGEN_DER].x;
  const giro = (p[PUNTA_NARIZ].x - izq) / (der - izq);

  if (angulo === "frontal") {
    if (giro < 0.4 || giro > 0.6) return { valido: false, mensaje: "Mira directamente de frente a la cámara." };
  } else if (angulo === "izquierda") {
    if (giro < 0.7) return { valido: false, mensaje: "Gira más la cabeza hacia TU IZQUIERDA." };
  } else if (angulo === "derecha") {
    if (giro > 0.3) return { valido: false, mensaje: "Gira más la cabeza hacia TU DERECHA." };
  }
  return { valido: true, mensaje: "¡Perfecto! Mantén la posición y toma la foto." };
}

function dibujarOvalo(canvas, estado) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  // Oscurece todo menos el ovalo, para que quede claro donde va la cara.
  ctx.fillStyle = "rgba(15, 29, 56, 0.55)";
  ctx.fillRect(0, 0, w, h);
  ctx.save();
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.ellipse(OVALO.cx * w, OVALO.cy * h, OVALO.rx * w, OVALO.ry * h, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  ctx.lineWidth = Math.max(4, w * 0.008);
  ctx.strokeStyle = estado === "valido" ? "#10b981" : estado === "casi" ? "#f59e0b" : "#ffffff";
  ctx.beginPath();
  ctx.ellipse(OVALO.cx * w, OVALO.cy * h, OVALO.rx * w, OVALO.ry * h, 0, 0, Math.PI * 2);
  ctx.stroke();
}

// Guia en vivo sobre un <video> con camara. `alCambiar({ valido, mensaje })` se llama cada vez
// que cambia el estado; el boton de "Tomar foto" se debe habilitar solo cuando `valido` es true.
export async function crearGuiaEnVivo({ video, canvas, alCambiar }) {
  const landmarker = await crearLandmarker("VIDEO");
  let angulo = "frontal";
  let activo = false;
  let ultimoTiempo = -1;
  let racha = 0;
  let ultimoMensaje = "";
  let ultimoValido = null;

  function reportar(valido, mensaje) {
    if (valido === ultimoValido && mensaje === ultimoMensaje) return;
    ultimoValido = valido;
    ultimoMensaje = mensaje;
    alCambiar({ valido, mensaje });
  }

  function ciclo() {
    if (!activo) return;
    if (video.readyState >= 2 && video.currentTime !== ultimoTiempo) {
      ultimoTiempo = video.currentTime;
      if (canvas.width !== video.videoWidth) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
      }
      const resultado = landmarker.detectForVideo(video, performance.now());
      const { valido, mensaje } = evaluarRostro(resultado.faceLandmarks, angulo);
      racha = valido ? racha + 1 : 0;
      const estable = racha >= CUADROS_ESTABLES;
      dibujarOvalo(canvas, estable ? "valido" : valido ? "casi" : "invalido");
      reportar(estable, valido && !estable ? "Mantén la posición…" : mensaje);
    }
    requestAnimationFrame(ciclo);
  }

  return {
    setAngulo(nuevo) {
      angulo = nuevo;
      racha = 0;
      ultimoValido = null;
    },
    iniciar() {
      if (activo) return;
      activo = true;
      racha = 0;
      ultimoValido = null;
      requestAnimationFrame(ciclo);
    },
    detener() {
      activo = false;
    },
  };
}

// Validacion de una foto SUBIDA desde el computador (sin camara en vivo): mismas reglas de
// angulo, tamaño y centrado, aplicadas a la imagen completa.
let landmarkerImagen = null;
export async function validarImagen(blob, angulo) {
  landmarkerImagen ??= await crearLandmarker("IMAGE");
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const resultado = landmarkerImagen.detect(img);
    return evaluarRostro(resultado.faceLandmarks, angulo, { encuadre: false });
  } finally {
    URL.revokeObjectURL(url);
  }
}
