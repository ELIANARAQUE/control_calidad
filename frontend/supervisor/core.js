// Nucleo compartido por TODAS las paginas del panel de supervisor (Centro de Monitoreo,
// Transcripciones, Detección de Lenguaje, Gestos y Expresiones, Historial y Reportes):
// login/autenticación, conexión WebSocket en vivo, estado acumulado (estaciones/contadores)
// y las funciones de render de eventos que se repiten en varias paginas. Cada pagina carga
// este archivo primero y despues su propio script con lo que le es especifico.

const Core = (() => {
  const TIPOS_CON_VEREDICTO = new Set(["alerta_postura", "alerta_lenguaje", "alerta_expresion", "alerta_ausencia"]);
  // La campana de notificaciones (badge + panel desplegable) solo debe avisar de lenguaje
  // inapropiado/mal trato -las de expresion y ausencia se revisan desde sus propias paginas,
  // pero llenar la campana con las 3 cosas mezcladas (mas de 180 con las viejas de postura)
  // le quitaba utilidad como "lo mas urgente para revisar ya".
  const TIPOS_NOTIFICABLES = new Set(["alerta_lenguaje"]);
  const MAX_EVENTOS_POR_ESTACION = 60;
  const COLORES_AVATAR = ["#0f9d68", "#6d28d9", "#1d4ed8", "#b45309", "#0f766e", "#7c3aed", "#0891b2"];
  // Mismas claves que usa /login/ (login unificado admin/empleado con verificacion facial):
  // el panel ya no tiene su propio formulario de usuario/clave, se autentica ahi y llega aca
  // con la sesion ya en sessionStorage.
  const CLAVE_TOKEN = "qamonitor.token";
  const CLAVE_ROL = "qamonitor.rol";
  const CLAVE_FOCO = "qamonitor.supervisor.estacionFoco";

  let tokenSesion = sessionStorage.getItem(CLAVE_TOKEN);
  const estaciones = new Map(); // estacion_id -> { empleado, sede, modulo, conectada, pendientes, eventos }
  const contadores = { pendientes: 0, transcripciones: 0, porTipo: { alerta_postura: 0, alerta_lenguaje: 0, alerta_expresion: 0, alerta_ausencia: 0 } };
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
    ws.onclose = async (ev) => {
      if (ev.code === 4401) {
        cerrarSesionLocal();
        return;
      }
      // El servidor cierra el socket ANTES de aceptarlo cuando el token es invalido (para
      // rechazar la conexion desde el handshake), y en ese caso el navegador nunca entrega el
      // codigo 4401 -llega como un cierre generico (normalmente 1006)-, asi que sin esto el
      // panel se quedaba reintentando cada 3s para siempre en vez de pedir reingresar cuando
      // el token quedaba invalido (ej. el servidor se reinicio y perdio las sesiones en memoria).
      try {
        const resp = await apiFetch("/api/estaciones");
        if (resp.status === 401 || resp.status === 403) {
          cerrarSesionLocal();
          return;
        }
      } catch (err) {
        // sin conexion al servidor: no se puede saber si el token sigue siendo valido, se
        // reintenta normalmente mas abajo
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
      case "alerta_ausencia":
        return { icono: "person_off", texto: evento.detalle, etiqueta: "Ausencia" };
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

  // Solo lenguaje/mal trato cuenta para la campana (ver TIPOS_NOTIFICABLES): las de expresion
  // y ausencia se revisan desde sus propias paginas, no compiten por atencion inmediata.
  function eventosPendientesNotificables() {
    const combinado = [];
    for (const [id, datos] of estaciones) {
      for (const evento of datos.eventos) {
        if (TIPOS_NOTIFICABLES.has(evento.tipo) && !evento.veredicto) {
          combinado.push({ ...evento, estacion_id: evento.estacion_id || id });
        }
      }
    }
    combinado.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    return combinado;
  }

  // --- Badge de campana (contador de pendientes en la topbar, presente en todas las paginas) ---
  function actualizarBadgeCampana() {
    const badgeCampana = document.getElementById("badgeCampana");
    if (!badgeCampana) return;
    const pendientesNotificables = eventosPendientesNotificables().length;
    if (pendientesNotificables > 0) {
      badgeCampana.textContent = pendientesNotificables;
      badgeCampana.classList.remove("hidden");
      badgeCampana.classList.add("flex");
    } else {
      badgeCampana.classList.add("hidden");
    }
  }

  // --- Panel desplegable de la campana: la campana solo actualizaba el numero, pero nunca
  // abria nada al hacer click (no tenia ningun listener) -se agrega aqui, una sola vez, para
  // que funcione igual en todas las paginas que tienen la campana en su topbar. Muestra las
  // alertas de lenguaje/mal trato de TODAS las estaciones que aun no tienen veredicto, para
  // poder revisarlas sin tener que ir pagina por pagina buscandolas.
  function iniciarCampanaNotificaciones() {
    const btnCampana = document.getElementById("btnCampana");
    if (!btnCampana || btnCampana.dataset.campanaLista) return;
    btnCampana.dataset.campanaLista = "1";

    const envoltorio = document.createElement("div");
    envoltorio.className = "relative";
    btnCampana.parentNode.insertBefore(envoltorio, btnCampana);
    envoltorio.appendChild(btnCampana);

    const panel = document.createElement("div");
    panel.id = "panelCampana";
    panel.className =
      "oculto absolute right-0 top-full mt-2 w-96 max-w-[90vw] max-h-[70vh] overflow-y-auto " +
      "bg-surface-container-lowest rounded-xl shadow-xl border border-surface-container-high z-50 " +
      "p-space-sm flex flex-col gap-space-xs";
    envoltorio.appendChild(panel);

    const eventosPendientes = eventosPendientesNotificables;

    function estaAbierto() {
      return !panel.classList.contains("oculto");
    }

    function renderizarPanel() {
      const pendientes = eventosPendientes();
      panel.innerHTML = "";

      const titulo = document.createElement("div");
      titulo.className =
        "font-headline-sm text-headline-sm text-on-surface font-bold px-space-xs pb-space-xs border-b border-surface-container-low sticky top-0 bg-surface-container-lowest";
      titulo.textContent = `Lenguaje / mal trato pendientes (${pendientes.length})`;
      panel.appendChild(titulo);

      if (pendientes.length === 0) {
        const vacio = document.createElement("p");
        vacio.className = "vacio-feed";
        vacio.textContent = "No hay alertas pendientes por revisar.";
        panel.appendChild(vacio);
        return;
      }
      for (const evento of pendientes.slice(0, 50)) {
        panel.appendChild(crearElementoEvento(evento, true, renderizarPanel));
      }
    }

    btnCampana.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (estaAbierto()) {
        panel.classList.add("oculto");
      } else {
        renderizarPanel();
        panel.classList.remove("oculto");
      }
    });
    document.addEventListener("click", (ev) => {
      if (estaAbierto() && !envoltorio.contains(ev.target)) panel.classList.add("oculto");
    });
    listenersEvento.push(() => {
      if (estaAbierto()) renderizarPanel();
    });
    listenersListo.push(() => {
      if (estaAbierto()) renderizarPanel();
    });
  }
  listenersEvento.push(actualizarBadgeCampana);
  listenersListo.push(actualizarBadgeCampana);

  // --- Sesión: login / logout (presente en todas las paginas) ---
  function cerrarSesionLocal() {
    sessionStorage.removeItem(CLAVE_TOKEN);
    sessionStorage.removeItem(CLAVE_ROL);
    tokenSesion = null;
    window.location.href = "/login/";
  }

  function marcarNavActiva() {
    const pagina = document.body.dataset.pagina;
    if (!pagina) return;
    document.querySelectorAll(`.nav-link[data-pagina="${pagina}"]`).forEach((el) => el.classList.add("activa"));
  }

  // El panel ya no tiene su propio formulario de usuario/clave: el login (credenciales +
  // verificacion facial) vive en /login/, compartido con la estacion de empleado. Aqui solo
  // se exige que ya exista una sesion valida CON ROL ADMIN -sin eso, se manda para alla-.
  function iniciar(alListo) {
    const appContenido = document.getElementById("appContenido");

    async function iniciarPagina() {
      appContenido?.classList.remove("oculto");
      marcarNavActiva();
      iniciarReloj();
      iniciarAvisoGlobal();
      iniciarCampanaNotificaciones();
      conectarWebSocket();
      // Estaciones activas primero (llena nombre/sede/modulo), despues eventos (asi el feed
      // ya puede mostrar el nombre del empleado en vez del id crudo de la estacion).
      await cargarEstacionesActivas();
      await cargarEventosRecientes();
      listenersListo.forEach((cb) => cb());
      if (alListo) alListo();
    }

    document.getElementById("btnCerrarSesion")?.addEventListener("click", async () => {
      try {
        await apiFetch("/api/auth/logout", { method: "POST" });
      } catch (err) {
        // si el servidor no responde igual se cierra la sesion localmente
      }
      cerrarSesionLocal();
    });

    const rol = sessionStorage.getItem(CLAVE_ROL);
    if (tokenSesion && rol === "admin") {
      iniciarPagina();
    } else {
      window.location.href = "/login/";
    }
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
