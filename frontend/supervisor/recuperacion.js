// Pagina "Recuperación": el administrador le asigna una contraseña nueva a un empleado que la
// olvido. Flujo: escribir el correo -> modal "verificando" -> si existe, modal con nueva
// contraseña + confirmacion -> modal de exito.

const formCorreo = document.getElementById("formCorreo");
const correoEl = document.getElementById("correoEmpleado");
const errorCorreoEl = document.getElementById("errorCorreo");
const modalVerificando = document.getElementById("modalVerificando");
const modalClave = document.getElementById("modalClave");
const modalExito = document.getElementById("modalExito");
const formClave = document.getElementById("formClave");
const claveNuevaEl = document.getElementById("claveNueva");
const confirmarClaveEl = document.getElementById("confirmarClave");
const errorClaveEl = document.getElementById("errorClave");
const btnCambiarClave = document.getElementById("btnCambiarClave");

let correoVerificado = null;

async function detalleError(resp) {
  const cuerpo = await resp.json().catch(() => ({}));
  if (Array.isArray(cuerpo.detail)) return cuerpo.detail.map((d) => d.msg).join("; ");
  return typeof cuerpo.detail === "string" ? cuerpo.detail : "HTTP " + resp.status;
}

function mostrarError(el, texto) {
  el.textContent = texto;
  el.classList.toggle("oculto", !texto);
}

correoEl.addEventListener("input", () => {
  correoEl.value = correoEl.value.replace(/\s/g, "");
  mostrarError(errorCorreoEl, "");
});

for (const el of [claveNuevaEl, confirmarClaveEl]) {
  el.addEventListener("input", () => {
    el.value = el.value.replace(/\s/g, "");
    mostrarError(errorClaveEl, "");
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

function limpiarClaves() {
  for (const el of [claveNuevaEl, confirmarClaveEl]) {
    el.value = "";
    el.type = "password";
  }
  document.querySelectorAll(".btn-ojo .material-symbols-outlined").forEach((i) => (i.textContent = "visibility"));
  mostrarError(errorClaveEl, "");
}

formCorreo.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const correo = correoEl.value.trim();
  if (!correo) return mostrarError(errorCorreoEl, "Escribe el correo del empleado");

  mostrarError(errorCorreoEl, "");
  modalVerificando.classList.remove("oculto");
  try {
    const resp = await Core.apiFetch("/api/auth/recuperacion/verificar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correo }),
    });
    if (!resp.ok) throw new Error(await detalleError(resp));
    const datos = await resp.json();
    correoVerificado = correo;
    document.getElementById("textoCuenta").textContent = `${datos.nombre} · ${correo}`;
    limpiarClaves();
    modalClave.classList.remove("oculto");
    claveNuevaEl.focus();
  } catch (err) {
    mostrarError(errorCorreoEl, err.message);
  } finally {
    modalVerificando.classList.add("oculto");
  }
});

document.getElementById("btnCancelarClave").addEventListener("click", () => {
  modalClave.classList.add("oculto");
  limpiarClaves();
  correoVerificado = null;
});

formClave.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const clave = claveNuevaEl.value;
  if (!clave) return mostrarError(errorClaveEl, "Digite la nueva contraseña");
  if (clave !== confirmarClaveEl.value) return mostrarError(errorClaveEl, "Las contraseñas no coinciden");

  btnCambiarClave.disabled = true;
  try {
    const resp = await Core.apiFetch("/api/auth/recuperacion/cambiar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correo: correoVerificado, clave, confirmar_clave: confirmarClaveEl.value }),
    });
    if (!resp.ok) throw new Error(await detalleError(resp));
    const datos = await resp.json();
    modalClave.classList.add("oculto");
    limpiarClaves();
    document.getElementById("textoExito").textContent =
      `Se cambió la contraseña del empleado ${datos.nombre} (${correoVerificado}). Ya puede iniciar sesión con la nueva contraseña.`;
    modalExito.classList.remove("oculto");
    correoEl.value = "";
    correoVerificado = null;
  } catch (err) {
    mostrarError(errorClaveEl, err.message);
  } finally {
    btnCambiarClave.disabled = false;
  }
});

document.getElementById("btnCerrarExito").addEventListener("click", () => modalExito.classList.add("oculto"));

Core.iniciar(() => {});
