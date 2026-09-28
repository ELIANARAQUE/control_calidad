// Formulario de registro de cuentas (empleado/admin): validaciones en vivo por campo, modal de
// foto (solo con la camara y la guia del ovalo: no se aceptan archivos subidos), y el flujo de confirmacion con clave de
// super-admin cuando se elige el rol "Administrador".

const REGEX_NOMBRE = /^[A-Za-zÀ-ÿ\s]*$/;
const REGEX_DOCUMENTO = /^[0-9]*$/;
const DOMINIO_CORREO = "@universitariadecolombia.edu.co";
const MENSAJE_CORREO = `El correo no puede tener espacios y debe terminar en ${DOMINIO_CORREO}`;

// Las dos unicas reglas del correo: sin espacios y terminado en el dominio institucional.
function correoValido(correo) {
  return !/\s/.test(correo) && correo.toLowerCase().endsWith(DOMINIO_CORREO) && correo.length > DOMINIO_CORREO.length;
}

const form = document.getElementById("formRegistro");
const nombreEl = document.getElementById("nombre");
const tipoDocumentoEl = document.getElementById("tipoDocumento");
const numeroDocumentoEl = document.getElementById("numeroDocumento");
const correoEl = document.getElementById("correo");
const claveEl = document.getElementById("clave");
const confirmarClaveEl = document.getElementById("confirmarClave");
const errorRegistro = document.getElementById("errorRegistro");

// Tres fotos obligatorias: frontal y ambos perfiles (asi el login facial reconoce a la
// persona aunque no quede perfectamente de frente a la camara).
const fotos = { frontal: null, izquierda: null, derecha: null };
const INSTRUCCION_ANGULO = {
  frontal: "Foto FRONTAL: mira directo a la cámara, rostro completo y centrado.",
  izquierda: "Foto LATERAL IZQUIERDA: gira la cabeza hacia tu izquierda unos 45° (tres cuartos, no perfil completo).",
  derecha: "Foto LATERAL DERECHA: gira la cabeza hacia tu derecha unos 45° (tres cuartos, no perfil completo).",
};
const TITULO_ANGULO = { frontal: "Foto frontal", izquierda: "Foto lateral izquierda", derecha: "Foto lateral derecha" };
let anguloActual = "frontal";

// --- Validaciones en vivo: se bloquea la tecla en vez de solo avisar despues ---
nombreEl.addEventListener("input", () => {
  if (!REGEX_NOMBRE.test(nombreEl.value)) {
    nombreEl.value = nombreEl.value.replace(/[^A-Za-zÀ-ÿ\s]/g, "");
  }
});

numeroDocumentoEl.addEventListener("input", () => {
  if (!REGEX_DOCUMENTO.test(numeroDocumentoEl.value)) {
    numeroDocumentoEl.value = numeroDocumentoEl.value.replace(/[^0-9]/g, "");
  }
});

const ayudaCorreoEl = document.getElementById("ayudaCorreo");
correoEl.addEventListener("input", () => {
  correoEl.value = correoEl.value.replace(/\s/g, "");
  correoEl.classList.remove("campo-error");
  ayudaCorreoEl.textContent = `Solo correo institucional (${DOMINIO_CORREO}).`;
  ayudaCorreoEl.className = "text-xs text-[#9b93b5]";
});
// Al salir del campo se avisa de una vez si el dominio no es el institucional.
correoEl.addEventListener("blur", () => {
  const valor = correoEl.value.trim();
  if (valor && !correoValido(valor)) {
    correoEl.classList.add("campo-error");
    ayudaCorreoEl.textContent = MENSAJE_CORREO;
    ayudaCorreoEl.className = "text-xs text-red-600 font-semibold";
  }
});

for (const el of [claveEl, confirmarClaveEl]) {
  el.addEventListener("input", () => {
    el.value = el.value.replace(/\s/g, "");
  });
}

document.querySelectorAll(".btn-ojo").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.target);
    const mostrar = input.type === "password";
    input.type = mostrar ? "text" : "password";
    btn.querySelector(".material-symbols-outlined").textContent = mostrar ? "visibility_off" : "visibility";
  });
});

// --- Tipos de documento (catalogo real, desde la base de datos) ---
async function cargarTiposDocumento() {
  try {
    const resp = await fetch("/api/auth/tipos-documento");
    const tipos = await resp.json();
    tipoDocumentoEl.innerHTML = tipos.map((t) => `<option value="${t.id}">${t.nombre}</option>`).join("");
  } catch (err) {
    tipoDocumentoEl.innerHTML = '<option value="">No se pudo cargar</option>';
  }
}
cargarTiposDocumento();

// --- Modal de foto: solo con la camara ---
const modalFoto = document.getElementById("modalFoto");
const videoRegistro = document.getElementById("videoRegistro");
const canvasRegistro = document.getElementById("canvasRegistro");
const btnTomarFoto = document.getElementById("btnTomarFoto");
let streamRegistro = null;

document.querySelectorAll(".slot-foto").forEach((slot) => {
  slot.addEventListener("click", () => {
    anguloActual = slot.dataset.angulo;
    document.getElementById("tituloModalFoto").textContent = TITULO_ANGULO[anguloActual];
    document.getElementById("instruccionAngulo").textContent = INSTRUCCION_ANGULO[anguloActual];
    modalFoto.classList.remove("oculto");
    abrirCamaraRegistro();
  });
});

function guardarFoto(blob) {
  fotos[anguloActual] = blob;
  const slot = document.querySelector(`.slot-foto[data-angulo="${anguloActual}"]`);
  slot.classList.remove("border-dashed");
  slot.classList.add("border-[#10b981]");
  slot.innerHTML = `<img class="w-full h-full object-cover" src="${URL.createObjectURL(blob)}" alt="${TITULO_ANGULO[anguloActual]}" />`;
  cerrarModalFoto();
}

// Guia con ovalo (ver /comun/guia-rostro.js): el boton "Tomar foto" solo se habilita cuando la
// cara esta dentro del ovalo y en el angulo pedido para esa foto.
const mensajeGuia = document.getElementById("mensajeGuiaRegistro");
const moduloGuia = import("/comun/guia-rostro.js");
let guia = null;

function mostrarMensajeGuia(texto, valido) {
  mensajeGuia.textContent = texto;
  mensajeGuia.className =
    "text-sm font-semibold text-center rounded-lg px-3 py-2 " +
    (valido ? "bg-[#d1fae5] text-[#065f46]" : "bg-[#eef1f8] text-[#0f1c30]");
}

function cerrarModalFoto() {
  guia?.detener();
  streamRegistro?.getTracks().forEach((t) => t.stop());
  streamRegistro = null;
  btnTomarFoto.disabled = true;
  modalFoto.classList.add("oculto");
}
document.getElementById("btnCancelarFoto").addEventListener("click", cerrarModalFoto);

async function abrirCamaraRegistro() {
  btnTomarFoto.disabled = true;
  mostrarMensajeGuia("Cargando guía de cámara…", false);
  try {
    streamRegistro = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    videoRegistro.srcObject = streamRegistro;
    const { crearGuiaEnVivo } = await moduloGuia;
    guia ??= await crearGuiaEnVivo({
      video: videoRegistro,
      canvas: document.getElementById("guiaRegistro"),
      alCambiar: ({ valido, mensaje }) => {
        btnTomarFoto.disabled = !valido;
        mostrarMensajeGuia(mensaje, valido);
      },
    });
    guia.setAngulo(anguloActual);
    guia.iniciar();
  } catch (err) {
    mostrarMensajeGuia("No se pudo iniciar la cámara o la guía: " + err.message, false);
  }
}

btnTomarFoto.addEventListener("click", () => {
  if (btnTomarFoto.disabled) return;
  canvasRegistro.width = videoRegistro.videoWidth;
  canvasRegistro.height = videoRegistro.videoHeight;
  canvasRegistro.getContext("2d").drawImage(videoRegistro, 0, 0);
  canvasRegistro.toBlob((blob) => guardarFoto(blob), "image/jpeg", 0.92);
});

// --- Modal de super-admin (solo si el rol elegido es "admin") ---
const modalSuperAdmin = document.getElementById("modalSuperAdmin");
const claveSuperAdminEl = document.getElementById("claveSuperAdmin");
const errorSuperAdmin = document.getElementById("errorSuperAdmin");
let resolverModalSuperAdmin = null;

function pedirClaveSuperAdmin() {
  return new Promise((resolve) => {
    resolverModalSuperAdmin = resolve;
    claveSuperAdminEl.value = "";
    errorSuperAdmin.classList.add("oculto");
    modalSuperAdmin.classList.remove("oculto");
  });
}
document.getElementById("btnCancelarSuperAdmin").addEventListener("click", () => {
  modalSuperAdmin.classList.add("oculto");
  resolverModalSuperAdmin?.(null);
});
document.getElementById("btnConfirmarSuperAdmin").addEventListener("click", () => {
  const clave = claveSuperAdminEl.value;
  if (!clave) {
    errorSuperAdmin.textContent = "Ingresa la clave de super-admin";
    errorSuperAdmin.classList.remove("oculto");
    return;
  }
  modalSuperAdmin.classList.add("oculto");
  resolverModalSuperAdmin?.(clave);
});

// --- Envio del formulario ---
form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errorRegistro.classList.add("oculto");

  const rol = form.querySelector('input[name="rol"]:checked').value;

  if (!nombreEl.value.trim()) return mostrarError("El nombre es obligatorio");
  if (!numeroDocumentoEl.value.trim()) return mostrarError("El número de documento es obligatorio");
  if (!correoValido(correoEl.value.trim())) {
    correoEl.classList.add("campo-error");
    return mostrarError(MENSAJE_CORREO);
  }
  if (claveEl.value.length === 0) return mostrarError("La contraseña es obligatoria");
  if (claveEl.value !== confirmarClaveEl.value) return mostrarError("Las contraseñas no coinciden");
  const faltantes = Object.keys(fotos).filter((a) => !fotos[a]).map((a) => TITULO_ANGULO[a].toLowerCase());
  if (faltantes.length) return mostrarError("Faltan fotos: " + faltantes.join(", "));

  let claveSuperAdmin = null;
  if (rol === "admin") {
    claveSuperAdmin = await pedirClaveSuperAdmin();
    if (!claveSuperAdmin) return; // el usuario cancelo el modal
  }

  const datosForm = new FormData();
  datosForm.append("nombre", nombreEl.value.trim());
  datosForm.append("tipo_documento_id", tipoDocumentoEl.value);
  datosForm.append("numero_documento", numeroDocumentoEl.value.trim());
  datosForm.append("correo", correoEl.value.trim());
  datosForm.append("clave", claveEl.value);
  datosForm.append("confirmar_clave", confirmarClaveEl.value);
  datosForm.append("rol", rol);
  if (claveSuperAdmin) datosForm.append("clave_super_admin", claveSuperAdmin);
  datosForm.append("foto_frontal", fotos.frontal, "frontal.jpg");
  datosForm.append("foto_izquierda", fotos.izquierda, "izquierda.jpg");
  datosForm.append("foto_derecha", fotos.derecha, "derecha.jpg");

  const modalCargando = document.getElementById("modalCargando");
  const botonEnviar = form.querySelector('button[type="submit"]');
  modalCargando.classList.remove("oculto");
  botonEnviar.disabled = true;
  try {
    const resp = await fetch("/api/auth/registro", { method: "POST", body: datosForm });
    const datos = await resp.json();
    if (!resp.ok) {
      throw new Error(
        Array.isArray(datos.detail) ? datos.detail.map((d) => d.msg).join("; ") : datos.detail || "No se pudo crear la cuenta"
      );
    }

    document.getElementById("textoExito").textContent =
      rol === "admin"
        ? "Tu cuenta de administrador fue creada. Ahora inicia sesión en el panel de supervisor."
        : "Tu cuenta fue creada. Ahora inicia sesión para ir a tu estación de trabajo.";
    document.getElementById("modalExito").classList.remove("oculto");
    document.getElementById("btnIrLogin").onclick = () => (window.location.href = "/login/");
  } catch (err) {
    mostrarError(err.message);
  } finally {
    modalCargando.classList.add("oculto");
    botonEnviar.disabled = false;
  }
});

function mostrarError(mensaje) {
  errorRegistro.textContent = mensaje;
  errorRegistro.classList.remove("oculto");
}
