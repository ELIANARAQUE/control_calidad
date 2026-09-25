// Formulario de registro de cuentas (empleado/admin): validaciones en vivo por campo, modal de
// foto (subir archivo o tomar con la camara), y el flujo de confirmacion con clave de
// super-admin cuando se elige el rol "Administrador".

const REGEX_NOMBRE = /^[A-Za-zÀ-ÿ\s]*$/;
const REGEX_DOCUMENTO = /^[A-Za-z0-9]*$/;

const form = document.getElementById("formRegistro");
const nombreEl = document.getElementById("nombre");
const tipoDocumentoEl = document.getElementById("tipoDocumento");
const numeroDocumentoEl = document.getElementById("numeroDocumento");
const correoEl = document.getElementById("correo");
const claveEl = document.getElementById("clave");
const confirmarClaveEl = document.getElementById("confirmarClave");
const errorRegistro = document.getElementById("errorRegistro");
const previewFoto = document.getElementById("previewFoto");
const textoBotonFoto = document.getElementById("textoBotonFoto");

let fotoBlob = null;

// --- Validaciones en vivo: se bloquea la tecla en vez de solo avisar despues ---
nombreEl.addEventListener("input", () => {
  if (!REGEX_NOMBRE.test(nombreEl.value)) {
    nombreEl.value = nombreEl.value.replace(/[^A-Za-zÀ-ÿ\s]/g, "");
  }
});

numeroDocumentoEl.addEventListener("input", () => {
  if (!REGEX_DOCUMENTO.test(numeroDocumentoEl.value)) {
    numeroDocumentoEl.value = numeroDocumentoEl.value.replace(/[^A-Za-z0-9]/g, "");
  }
});

correoEl.addEventListener("input", () => {
  correoEl.value = correoEl.value.replace(/\s/g, "");
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

// --- Modal de foto: subir archivo o tomar con la camara ---
const modalFoto = document.getElementById("modalFoto");
const inputArchivoFoto = document.getElementById("inputArchivoFoto");
const wrapCamaraRegistro = document.getElementById("wrapCamaraRegistro");
const videoRegistro = document.getElementById("videoRegistro");
const canvasRegistro = document.getElementById("canvasRegistro");
const btnTomarFoto = document.getElementById("btnTomarFoto");
let streamRegistro = null;

document.getElementById("btnAbrirFoto").addEventListener("click", () => {
  modalFoto.classList.remove("oculto");
});

function cerrarModalFoto() {
  streamRegistro?.getTracks().forEach((t) => t.stop());
  streamRegistro = null;
  wrapCamaraRegistro.classList.add("oculto");
  btnTomarFoto.classList.add("oculto");
  modalFoto.classList.add("oculto");
}
document.getElementById("btnCancelarFoto").addEventListener("click", cerrarModalFoto);

document.getElementById("btnModoArchivo").addEventListener("click", () => {
  wrapCamaraRegistro.classList.add("oculto");
  btnTomarFoto.classList.add("oculto");
  inputArchivoFoto.click();
});

inputArchivoFoto.addEventListener("change", () => {
  const archivo = inputArchivoFoto.files[0];
  if (!archivo) return;
  fotoBlob = archivo;
  previewFoto.src = URL.createObjectURL(archivo);
  previewFoto.classList.remove("oculto");
  textoBotonFoto.textContent = "Cambiar foto";
  cerrarModalFoto();
});

document.getElementById("btnModoCamara").addEventListener("click", async () => {
  wrapCamaraRegistro.classList.remove("oculto");
  btnTomarFoto.classList.remove("oculto");
  try {
    streamRegistro = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 } });
    videoRegistro.srcObject = streamRegistro;
  } catch (err) {
    alert("No se pudo acceder a la cámara: " + err.message);
  }
});

btnTomarFoto.addEventListener("click", () => {
  canvasRegistro.width = videoRegistro.videoWidth;
  canvasRegistro.height = videoRegistro.videoHeight;
  canvasRegistro.getContext("2d").drawImage(videoRegistro, 0, 0);
  canvasRegistro.toBlob((blob) => {
    fotoBlob = blob;
    previewFoto.src = URL.createObjectURL(blob);
    previewFoto.classList.remove("oculto");
    textoBotonFoto.textContent = "Cambiar foto";
    cerrarModalFoto();
  }, "image/jpeg", 0.92);
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
  if (!/^[^\s@]+@[^\s@]+\.com$/.test(correoEl.value.trim())) {
    return mostrarError('El correo debe contener "@" y terminar en ".com", sin espacios');
  }
  if (claveEl.value.length === 0) return mostrarError("La contraseña es obligatoria");
  if (claveEl.value !== confirmarClaveEl.value) return mostrarError("Las contraseñas no coinciden");
  if (!fotoBlob) return mostrarError('Debes subir o tomar una foto en "Subir foto"');

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
  datosForm.append("foto", fotoBlob, "rostro.jpg");

  try {
    const resp = await fetch("/api/auth/registro", { method: "POST", body: datosForm });
    const datos = await resp.json();
    if (!resp.ok) throw new Error(datos.detail || "No se pudo crear la cuenta");

    document.getElementById("textoExito").textContent =
      rol === "admin"
        ? "Tu cuenta de administrador fue creada. Ahora inicia sesión en el panel de supervisor."
        : "Tu cuenta fue creada. Ahora inicia sesión para ir a tu estación de trabajo.";
    document.getElementById("modalExito").classList.remove("oculto");
    document.getElementById("btnIrLogin").onclick = () => (window.location.href = "/login/");
  } catch (err) {
    mostrarError(err.message);
  }
});

function mostrarError(mensaje) {
  errorRegistro.textContent = mensaje;
  errorRegistro.classList.remove("oculto");
}
