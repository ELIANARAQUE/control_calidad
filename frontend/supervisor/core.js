// Nucleo compartido por TODAS las paginas del panel de supervisor (Centro de Monitoreo,
// Transcripciones, Detección de Lenguaje, Gestos y Expresiones, Historial y Reportes):
// login/autenticación, conexión WebSocket en vivo, estado acumulado (estaciones/contadores)
// y las funciones de render de eventos que se repiten en varias paginas. Cada pagina carga
// este archivo primero y despues su propio script con lo que le es especifico.

const Core = (() => {
  const TIPOS_CON_VEREDICTO = new Set(["alerta_postura", "alerta_lenguaje", "alerta_expresion"]);
  const MAX_EVENTOS_POR_ESTACION = 60;
  const COLORES_AVATAR = ["#0f9d68", "#6d28d9", "#1d4ed8", "#b45309", "#0f766e", "#7c3aed", "#0891b2"];
  const CLAVE_TOKEN = "qamonitor.supervisor.token";
  const CLAVE_FOCO = "qamonitor.supervisor.estacionFoco";

  let tokenSesion = sessionStorage.getItem(CLAVE_TOKEN);
  const estaciones = new Map(); // estacion_id -> { empleado, sede, modulo, conectada, pendientes, eventos }
  const contadores = { pendientes: 0, transcripciones: 0, porTipo: { alerta_postura: 0, alerta_lenguaje: 0, alerta_expresion: 0 } };
  const listenersEvento = [];
  const listenersListo = [];

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
    const toastEl = document.getElementById("toast");
    if (!toastEl) return;
    toastEl.textContent = texto;
    toastEl.classList.remove("oculto");
    clearTimeout(mostrarToast._t);
    mostrarToast._t = setTimeout(() => toastEl.classList.add("oculto"), 3500);
  }

  function obtenerEstacion(estacionId) {
    if (!estaciones.has(estacionId)) {
      estaciones.set(estacionId, { empleado: null, sede: null, modulo: null, conectada: false, pendientes: 0, eventos: [] });
    }
    return estaciones.get(estacionId);
  }

  function procesarEvento(evento) {
    const estacion = obtenerEstacion(evento.estacion_id);
    // Los eventos que vienen del historial (`cargarEventosRecientes`) traen el nombre del
    // empleado en el propio evento (la estacion puede ya no estar conectada, o haberse
    // desconectado antes de que esta pagina cargara la lista de "activas"): sin esto se veia
    // el UUID crudo de la estacion en vez del nombre en Gestos/Lenguaje/Transcripciones.
    if (evento.empleado && !estacion.empleado) estacion.empleado = evento.empleado;
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
          contadores.porTipo[evento.tipo] = (contadores.porTipo[evento.tipo] || 0) + 1;
          // Solo cuenta como "pendiente" si todavia no tiene veredicto: los eventos que
          // llegan en vivo siempre estan sin revisar, pero los que se cargan desde el
          // historial (`cargarEventosRecientes`) pueden ya venir confirmados/descartados.
          if (!evento.veredicto) {
            contadores.pendientes++;
            estacion.pendientes++;
          }
        }
        estacion.eventos.unshift(evento);
    }
    if (estacion.eventos.length > MAX_EVENTOS_POR_ESTACION) estacion.eventos.length = MAX_EVENTOS_POR_ESTACION;
    listenersEvento.forEach((cb) => cb(evento));
  }

  function conectarWebSocket() {
    const estadoTextoEl = document.getElementById("estadoTexto");
    const puntoEl = document.getElementById("punto");
    const protocolo = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(conToken(`${protocolo}://${location.host}/ws/supervisor`));

    ws.onopen = () => {
      if (estadoTextoEl) estadoTextoEl.textContent = "Conectado en vivo";
      puntoEl?.classList.add("conectado");
    };
    ws.onclose = (ev) => {
      if (ev.code === 4401) {
        cerrarSesionLocal();
        return;
      }
      if (estadoTextoEl) estadoTextoEl.textContent = "Desconectado. Reintentando…";
      puntoEl?.classList.remove("conectado");
      setTimeout(conectarWebSocket, 3000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (msg) => procesarEvento(JSON.parse(msg.data));
  }

  async function cargarEstacionesActivas() {
    try {
      const resp = await apiFetch("/api/estaciones");
      if (resp.status === 401) return cerrarSesionLocal();
      if (!resp.ok) return;
      const lista = await resp.json();
      for (const item of lista) {
        const estacion = obtenerEstacion(item.estacion_id);
        estacion.empleado = item.empleado_nombre;
        estacion.sede = item.sede;
        estacion.modulo = item.modulo;
        estacion.conectada = true;
      }
    } catch (err) {
      // el panel sigue funcionando solo con lo que llegue por WebSocket a partir de ahora
    }
  }

  // Sin esto, el feed de cada pagina arrancaba vacio en cada carga/navegacion (solo se llenaba
  // con lo que llegara en vivo por WebSocket MIENTRAS esa pagina estuviera abierta), aunque los
  // datos seguian intactos en la base de datos -por eso se veian bien en Historial/Excel pero
  // "desaparecian" al cambiar de pestaña del menu y volver.
  async function cargarEventosRecientes() {
    try {
      const resp = await apiFetch("/api/eventos/recientes");
      if (resp.status === 401) return cerrarSesionLocal();
      if (!resp.ok) return;
      const eventos = await resp.json();
      for (const evento of eventos) procesarEvento(evento);
    } catch (err) {
      // el panel sigue funcionando solo con lo que llegue por WebSocket a partir de ahora
    }
  }

  // --- Foco en una sola estacion (para cuando hay varias camaras conectadas a la vez y las
  // transcripciones/alertas de todas juntas se vuelven dificiles de seguir): se guarda en
  // sessionStorage (no en memoria) para que sobreviva al navegar entre paginas del panel,
  // que son recargas completas de pagina, no una SPA.
  function obtenerFoco() {
    return sessionStorage.getItem(CLAVE_FOCO);
  }
  function establecerFoco(estacionId) {
    sessionStorage.setItem(CLAVE_FOCO, estacionId);
  }
  function quitarFoco() {
    sessionStorage.removeItem(CLAVE_FOCO);
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

  async function enviarVeredicto(estacionId, alertaId, veredicto, contenedorAcciones, alRenderizar) {
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
      if (alRenderizar) alRenderizar();
    } catch (err) {
      contenedorAcciones.textContent = "Error al guardar: " + err.message;
    }
  }

  function crearElementoEvento(evento, mostrarNombreEstacion, alRenderizar) {
    const { icono, texto, etiqueta } = textoEvento(evento);
    const div = document.createElement("div");
    const esCritico = TIPOS_CON_VEREDICTO.has(evento.tipo);
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
        btnConfirmar.onclick = () => enviarVeredicto(evento.estacion_id, evento.alerta_id, "confirmada", acciones, alRenderizar);

        const btnDescartar = document.createElement("button");
        btnDescartar.textContent = "Falsa alarma";
        btnDescartar.className = "btn-veredicto btn-descartar";
        btnDescartar.onclick = () => enviarVeredicto(evento.estacion_id, evento.alerta_id, "falsa_alarma", acciones, alRenderizar);

        acciones.appendChild(btnConfirmar);
        acciones.appendChild(btnDescartar);
      }
      div.appendChild(acciones);
    }
    return div;
  }

  // --- Reloj de la topbar (presente en todas las paginas) ---
  function iniciarReloj() {
    const relojTexto = document.getElementById("relojTexto");
    if (!relojTexto) return;
    const actualizar = () => (relojTexto.textContent = new Date().toLocaleTimeString("es-CO", { hour12: false }));
    setInterval(actualizar, 1000);
    actualizar();
  }

  // --- Aviso global a estaciones (presente en varias paginas) ---
  function iniciarAvisoGlobal() {
    const modalAviso = document.getElementById("modalAviso");
    const textoAviso = document.getElementById("textoAviso");
    if (!modalAviso || !textoAviso) return;

    function abrir() {
      modalAviso.classList.remove("oculto");
      textoAviso.value = "";
      textoAviso.focus();
    }
    document.getElementById("btnAlertaGlobal")?.addEventListener("click", abrir);
    document.getElementById("btnAlertaGlobal2")?.addEventListener("click", abrir);
    document.getElementById("btnCancelarAviso")?.addEventListener("click", () => modalAviso.classList.add("oculto"));
    document.getElementById("btnEnviarAviso")?.addEventListener("click", async () => {
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
  }

  // --- Badge de campana (contador de pendientes en la topbar, presente en todas las paginas) ---
  function actualizarBadgeCampana() {
    const badgeCampana = document.getElementById("badgeCampana");
    if (!badgeCampana) return;
    if (contadores.pendientes > 0) {
      badgeCampana.textContent = contadores.pendientes;
      badgeCampana.classList.remove("hidden");
      badgeCampana.classList.add("flex");
    } else {
      badgeCampana.classList.add("hidden");
    }
  }
  listenersEvento.push(actualizarBadgeCampana);
  listenersListo.push(actualizarBadgeCampana);

  // --- Sesión: login / logout (presente en todas las paginas) ---
  function cerrarSesionLocal() {
    sessionStorage.removeItem(CLAVE_TOKEN);
    tokenSesion = null;
    location.reload();
  }

  function marcarNavActiva() {
    const pagina = document.body.dataset.pagina;
    if (!pagina) return;
    document.querySelectorAll(`.nav-link[data-pagina="${pagina}"]`).forEach((el) => el.classList.add("activa"));
  }

  function iniciar(alListo) {
    const pantallaLogin = document.getElementById("pantallaLogin");
    const appContenido = document.getElementById("appContenido");
    const formLogin = document.getElementById("formLogin");
    const loginError = document.getElementById("loginError");

    async function iniciarPagina() {
      pantallaLogin?.classList.add("oculto");
      appContenido?.classList.remove("oculto");
      marcarNavActiva();
      iniciarReloj();
      iniciarAvisoGlobal();
      conectarWebSocket();
      // Estaciones activas primero (llena nombre/sede/modulo), despues eventos (asi el feed
      // ya puede mostrar el nombre del empleado en vez del id crudo de la estacion).
      await cargarEstacionesActivas();
      await cargarEventosRecientes();
      listenersListo.forEach((cb) => cb());
      if (alListo) alListo();
    }

    formLogin?.addEventListener("submit", async (ev) => {
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
        iniciarPagina();
      } catch (err) {
        loginError.textContent = err.message;
        loginError.classList.remove("oculto");
      }
    });

    document.getElementById("btnCerrarSesion")?.addEventListener("click", async () => {
      try {
        await apiFetch("/api/auth/logout", { method: "POST" });
      } catch (err) {
        // si el servidor no responde igual se cierra la sesion localmente
      }
      cerrarSesionLocal();
    });

    if (tokenSesion) iniciarPagina();
  }

  return {
    estaciones, contadores, conToken, apiFetch, mostrarToast,
    onEvento: (cb) => listenersEvento.push(cb),
    onListo: (cb) => listenersListo.push(cb),
    colorAvatar, iniciales, hace, textoEvento, crearElementoEvento, enviarVeredicto,
    obtenerFoco, establecerFoco, quitarFoco,
    iniciar,
  };
})();
