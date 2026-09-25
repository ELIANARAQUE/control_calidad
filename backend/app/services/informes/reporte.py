"""Genera el reporte de evaluacion de un trabajador como archivo .xlsx (dos hojas: Resumen
y Detalle). Reemplaza el CSV global anterior -que mezclaba a todos los empleados en un solo
archivo disperso- por un documento individual, pensado para revisarse en una evaluacion.
"""
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ImagenExcel
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.db import RUTA_CAPTURAS, obtener_datos_reporte_trabajador

_ALTO_FILA_CON_FOTO = 58  # puntos: suficiente para una miniatura de ~70px de alto
_ANCHO_FOTO_COL_PX = 70

_AZUL_INSTITUCIONAL = "0F1D38"
_VERDE = "10B981"
_ROJO = "DC2626"
_GRIS_CLARO = "EEF1F8"

# Los timestamps se guardan en UTC (con "+00:00" al final); mostrarlos tal cual (sin convertir)
# hacia que el reporte se viera "corrido" 5 horas respecto a lo que de verdad paso en Colombia
# -al punto de que un evento de las 7pm local aparecia fechado al dia siguiente en el reporte-.
_ZONA_COLOMBIA = ZoneInfo("America/Bogota")


def _a_hora_colombia(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ZONA_COLOMBIA)


def _fila_encabezado(ws, fila: int, encabezados: list[str], color_fondo: str = _AZUL_INSTITUCIONAL) -> None:
    for col, texto in enumerate(encabezados, start=1):
        celda = ws.cell(row=fila, column=col, value=texto)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=color_fondo)
        celda.alignment = Alignment(vertical="center")


def _fecha_legible(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = _a_hora_colombia(iso)
    except ValueError:
        return iso
    return dt.strftime("%d/%m/%Y %H:%M")


def generar_reporte_trabajador_xlsx(nombre: str) -> bytes:
    datos = obtener_datos_reporte_trabajador(nombre)
    sesiones = datos["sesiones"]
    eventos = datos["eventos"]

    conexiones = [s for s in sesiones if s["tipo"] == "conexion"]
    sedes = sorted({s["sede"] for s in conexiones if s["sede"]})
    modulos = sorted({s["modulo"] for s in conexiones if s["modulo"]})
    primera = min((s["timestamp"] for s in conexiones), default=None)
    ultima = max((s["timestamp"] for s in conexiones), default=None)

    alertas = [e for e in eventos if e["categoria"].startswith("Alerta")]
    transcripciones = [e for e in eventos if e["categoria"] == "Transcripción"]
    confirmadas = sum(1 for a in alertas if a["veredicto"] == "confirmada")
    falsas = sum(1 for a in alertas if a["veredicto"] == "falsa_alarma")
    sin_revisar = sum(1 for a in alertas if a["veredicto"] == "Sin revisar")
    por_tipo = {"postura": 0, "lenguaje": 0, "expresion": 0, "ausencia": 0}
    for a in alertas:
        for tipo in por_tipo:
            if tipo in a["categoria"]:
                por_tipo[tipo] += 1

    wb = Workbook()

    # ---------------- Hoja "Resumen" ----------------
    ws = wb.active
    ws.title = "Resumen"
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:D1")
    ws["A1"] = f"Reporte de Desempeño — {nombre}"
    ws["A1"].font = Font(bold=True, size=16, color=_AZUL_INSTITUCIONAL)

    ws.merge_cells("A2:D2")
    ws["A2"] = "Universitaria de Colombia — Sistema de Control de Calidad del Servicio"
    ws["A2"].font = Font(italic=True, size=10, color="586174")

    ws["A3"] = "Generado el:"
    ws["B3"] = _fecha_legible(datetime.now(timezone.utc).isoformat())
    ws["A3"].font = Font(bold=True)

    filas_resumen = [
        ("Nombre del trabajador", nombre),
        ("Sede(s)", ", ".join(sedes) or "—"),
        ("Módulo(s) / ventanilla(s)", ", ".join(modulos) or "—"),
        ("Primera conexión registrada", _fecha_legible(primera)),
        ("Última conexión registrada", _fecha_legible(ultima)),
        ("Total de sesiones", len(conexiones)),
        ("Frases transcritas", len(transcripciones)),
        ("Total de alertas generadas", len(alertas)),
        ("  · Alertas de lenguaje inapropiado", por_tipo["lenguaje"]),
        ("  · Alertas de expresión facial negativa", por_tipo["expresion"]),
        ("  · Alertas de ausencia frente a la cámara", por_tipo["ausencia"]),
        ("  · Alertas de postura (heurística retirada, solo historial)", por_tipo["postura"]),
        ("Alertas confirmadas por el supervisor", confirmadas),
        ("Alertas descartadas (falsa alarma)", falsas),
        ("Alertas sin revisar todavía", sin_revisar),
    ]

    fila = 5
    _fila_encabezado(ws, fila, ["Indicador", "Valor"])
    fila += 1
    for etiqueta, valor in filas_resumen:
        ws.cell(row=fila, column=1, value=etiqueta)
        celda_valor = ws.cell(row=fila, column=2, value=valor)
        celda_valor.alignment = Alignment(horizontal="left")
        if fila % 2 == 0:
            for col in (1, 2):
                ws.cell(row=fila, column=col).fill = PatternFill("solid", fgColor=_GRIS_CLARO)
        fila += 1

    # Indicador de "calidad" visual simple: verde si no hay pendientes ni confirmadas, rojo
    # si hay confirmadas (indica incidentes reales verificados por el supervisor).
    fila += 1
    ws.cell(row=fila, column=1, value="Indicador general").font = Font(bold=True)
    celda_indicador = ws.cell(row=fila, column=2)
    if confirmadas > 0:
        celda_indicador.value = "Requiere seguimiento (hay alertas confirmadas)"
        celda_indicador.fill = PatternFill("solid", fgColor=_ROJO)
        celda_indicador.font = Font(bold=True, color="FFFFFF")
    elif sin_revisar > 0:
        celda_indicador.value = "Pendiente de revisión"
        celda_indicador.font = Font(bold=True)
    else:
        celda_indicador.value = "Sin incidentes confirmados"
        celda_indicador.fill = PatternFill("solid", fgColor=_VERDE)
        celda_indicador.font = Font(bold=True, color="FFFFFF")

    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 32

    # ---------------- Hoja "Detalle" ----------------
    ws2 = wb.create_sheet("Detalle")
    ws2.sheet_view.showGridLines = False
    encabezados = ["Fecha", "Hora", "Categoría", "Detalle", "Veredicto", "Foto"]
    _fila_encabezado(ws2, 1, encabezados)
    ws2.freeze_panes = "A2"

    for i, evento in enumerate(eventos, start=2):
        try:
            dt = _a_hora_colombia(evento["timestamp"])
            fecha_txt, hora_txt = dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            fecha_txt, hora_txt = evento["timestamp"], ""

        veredicto = evento["veredicto"]
        ws2.cell(row=i, column=1, value=fecha_txt)
        ws2.cell(row=i, column=2, value=hora_txt)
        ws2.cell(row=i, column=3, value=evento["categoria"])
        celda_detalle = ws2.cell(row=i, column=4, value=evento["detalle"])
        celda_detalle.alignment = Alignment(wrap_text=True, vertical="top")
        celda_veredicto = ws2.cell(row=i, column=5, value=veredicto)

        if veredicto == "confirmada":
            celda_veredicto.font = Font(bold=True, color=_ROJO)
        elif veredicto == "falsa_alarma":
            celda_veredicto.font = Font(color="586174")
        elif veredicto == "Sin revisar":
            celda_veredicto.font = Font(italic=True, color="B45309")

        # Foto de la alerta (si se pudo capturar en el momento): se embebe como imagen dentro
        # de la celda en vez de solo guardar la ruta, para que el reporte sea autocontenido y
        # el evaluador no tenga que ir a buscar el archivo en el servidor.
        captura_path = evento.get("captura_path")
        if captura_path:
            ruta_absoluta = (RUTA_CAPTURAS / captura_path).resolve()
            if RUTA_CAPTURAS.resolve() in ruta_absoluta.parents and ruta_absoluta.is_file():
                try:
                    imagen = ImagenExcel(str(ruta_absoluta))
                    imagen.height = 70
                    imagen.width = 70
                    ws2.add_image(imagen, f"F{i}")
                    ws2.row_dimensions[i].height = _ALTO_FILA_CON_FOTO
                except Exception:
                    ws2.cell(row=i, column=6, value="(no se pudo cargar la foto)")
            else:
                ws2.cell(row=i, column=6, value="(foto no disponible)")

        if i % 2 == 0:
            for col in range(1, 6):
                if not ws2.cell(row=i, column=col).fill.fgColor.rgb or ws2.cell(row=i, column=col).fill.fgColor.rgb == "00000000":
                    ws2.cell(row=i, column=col).fill = PatternFill("solid", fgColor=_GRIS_CLARO)

    anchos = [12, 10, 22, 60, 16, 12]
    for idx, ancho in enumerate(anchos, start=1):
        ws2.column_dimensions[get_column_letter(idx)].width = ancho

    if not eventos:
        ws2.cell(row=2, column=1, value="Sin eventos registrados para este trabajador todavía.")

    # ---------------- Hoja "Transcripciones" ----------------
    # Solo lo que la persona hablo, en orden, sin mezclarlo con alertas -para poder leer de
    # corrido "todo lo que dijo" durante sus sesiones, que es lo que se pidio: una vista
    # dedicada solo a la voz transcrita, organizada.
    ws3 = wb.create_sheet("Transcripciones")
    ws3.sheet_view.showGridLines = False
    _fila_encabezado(ws3, 1, ["Fecha", "Hora", "Transcripción"], color_fondo=_VERDE)
    ws3.freeze_panes = "A2"

    transcripciones = [e for e in eventos if e["categoria"] == "Transcripción"]
    fila_actual = 2
    for evento in transcripciones:
        try:
            dt = _a_hora_colombia(evento["timestamp"])
            fecha_txt, hora_txt = dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            fecha_txt, hora_txt = evento["timestamp"], ""

        ws3.cell(row=fila_actual, column=1, value=fecha_txt)
        ws3.cell(row=fila_actual, column=2, value=hora_txt)
        celda_texto = ws3.cell(row=fila_actual, column=3, value=evento["detalle"])
        celda_texto.alignment = Alignment(wrap_text=True, vertical="top")
        if fila_actual % 2 == 0:
            for col in (1, 2, 3):
                ws3.cell(row=fila_actual, column=col).fill = PatternFill("solid", fgColor=_GRIS_CLARO)
        fila_actual += 1

    if not transcripciones:
        ws3.cell(row=2, column=1, value="Sin transcripciones de voz registradas para este trabajador todavía.")

    ws3.column_dimensions["A"].width = 12
    ws3.column_dimensions["B"].width = 10
    ws3.column_dimensions["C"].width = 90

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
