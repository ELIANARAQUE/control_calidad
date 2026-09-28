"""Excel del historial general (pagina 'Historial y Reportes'): todo lo filtrado -o solo las
sesiones marcadas- desglosado en cuatro hojas:

  Resumen          totales del periodo y un resumen por empleado
  Sesiones         una fila por sesion: sede, modulo, inicio, fin, duracion y alertas por tipo
  Alertas          una fila por alerta, con los datos de su sesion y la foto del momento
  Pausas           una fila por cada almuerzo o break, con su duracion
  Transcripciones  una fila por frase transcrita, con los datos de su sesion
"""
import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ImagenExcel
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.core.db import RUTA_CAPTURAS
from app.core.seguridad import descifrar_bytes
from app.services.informes.reporte import _a_hora_colombia, _fecha_legible

_MORADO = "5B46D6"
_MORADO_OSCURO = "2B2156"
_LAVANDA = "F3EEFB"
_VERDE = "10B981"
_ROJO = "DC2626"
_GRIS = "6B6485"
_BORDE = Border(bottom=Side(style="thin", color="E6DDF5"))

_NOMBRE_TIPO = {
    "lenguaje": "Lenguaje inapropiado",
    "expresion": "Expresión negativa",
    "ausencia": "Ausencia",
    "expresion_positiva": "Expresión positiva",
    "postura": "Postura",
}
_NOMBRE_PAUSA = {"almuerzo": "Almuerzo", "break": "Break"}
_NOMBRE_VEREDICTO = {"confirmada": "Fue real", "falsa_alarma": "Falsa alarma", "sin_revisar": "Sin revisar"}


def _fecha(iso: str) -> str:
    return _a_hora_colombia(iso).strftime("%d/%m/%Y")


def _hora(iso: str) -> str:
    return _a_hora_colombia(iso).strftime("%H:%M:%S")


def _duracion(segundos: int) -> str:
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h} h {m} min" if h else f"{m} min {s} s" if m else f"{s} s"


def _titulo(ws, titulo: str, descripcion: str, columnas: int) -> int:
    """Encabezado comun de cada hoja. Devuelve la fila donde empieza la tabla."""
    ultima = get_column_letter(max(columnas, 2))
    ws.merge_cells(f"A1:{ultima}1")
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=15, color=_MORADO_OSCURO)
    ws.merge_cells(f"A2:{ultima}2")
    ws["A2"] = "Universitaria de Colombia — Sistema de Control de Calidad del Servicio"
    ws["A2"].font = Font(italic=True, size=10, color=_GRIS)
    ws.merge_cells(f"A3:{ultima}3")
    ws["A3"] = f"{descripcion} · Generado el {_fecha_legible(datetime.now(timezone.utc).isoformat())}"
    ws["A3"].font = Font(size=10, color=_GRIS)
    return 5


def _tabla(ws, fila: int, encabezados: list[str], filas: list[list], anchos: list[int], ajustar: set[int] = frozenset()) -> int:
    """Escribe encabezados + filas con estilo (encabezado morado, filas alternas, filtros de
    Excel y encabezado fijo). Devuelve la fila siguiente a la tabla."""
    for col, texto in enumerate(encabezados, start=1):
        celda = ws.cell(row=fila, column=col, value=texto)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=_MORADO)
        celda.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[fila].height = 30
    inicio_datos = fila + 1
    for i, valores in enumerate(filas):
        r = inicio_datos + i
        for col, valor in enumerate(valores, start=1):
            celda = ws.cell(row=r, column=col, value=valor)
            celda.border = _BORDE
            celda.alignment = Alignment(vertical="top", wrap_text=col in ajustar)
            if i % 2 == 1:
                celda.fill = PatternFill("solid", fgColor=_LAVANDA)
    for idx, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = ancho
    fin = inicio_datos + max(len(filas), 1) - 1
    if filas:
        ws.auto_filter.ref = f"A{fila}:{get_column_letter(len(encabezados))}{fin}"
    ws.freeze_panes = f"A{inicio_datos}"
    return fin + 1


def _foto(ruta_relativa: str | None) -> ImagenExcel | None:
    if not ruta_relativa:
        return None
    ruta = (RUTA_CAPTURAS / ruta_relativa).resolve()
    if RUTA_CAPTURAS.resolve() not in ruta.parents or not ruta.is_file():
        return None
    try:
        imagen = ImagenExcel(io.BytesIO(descifrar_bytes(ruta.read_bytes())))
    except Exception:
        return None
    imagen.width = imagen.height = 64
    return imagen


def generar_historial_xlsx(sesiones: list[dict], descripcion: str) -> bytes:
    wb = Workbook()

    # ------------------------------------------------------------------ Resumen
    ws = wb.active
    ws.title = "Resumen"
    ws.sheet_view.showGridLines = False
    fila = _titulo(ws, "Historial de sesiones — Resumen", descripcion, 9)

    alertas = [(s, a) for s in sesiones for a in s["alertas"]]
    negativas = [a for _, a in alertas if a["tipo"] != "expresion_positiva"]
    indicadores = [
        ("Sesiones", len(sesiones)),
        ("Empleados", len({s["nombre"] for s in sesiones})),
        ("Tiempo total de las sesiones", _duracion(sum(s["duracion_segundos"] for s in sesiones))),
        ("Tiempo efectivo (sin almuerzos ni breaks)", _duracion(sum(s["segundos_efectivos"] for s in sesiones))),
        ("Almuerzos (veces)", sum(s["veces_almuerzo"] for s in sesiones)),
        ("Tiempo total de almuerzo", _duracion(sum(s["segundos_almuerzo"] for s in sesiones))),
        ("Breaks (veces)", sum(s["veces_break"] for s in sesiones)),
        ("Tiempo total de break", _duracion(sum(s["segundos_break"] for s in sesiones))),
        ("Total de alertas", len(negativas)),
        ("  · Lenguaje inapropiado", sum(s["alertas_lenguaje"] for s in sesiones)),
        ("  · Expresión negativa", sum(s["alertas_expresion"] for s in sesiones)),
        ("  · Ausencia", sum(s["alertas_ausencia"] for s in sesiones)),
        ("Alertas confirmadas (fue real)", sum(a["veredicto"] == "confirmada" for a in negativas)),
        ("Alertas descartadas (falsa alarma)", sum(a["veredicto"] == "falsa_alarma" for a in negativas)),
        ("Alertas sin revisar", sum(a["veredicto"] == "sin_revisar" for a in negativas)),
        ("Expresiones positivas", sum(s["expresiones_positivas"] for s in sesiones)),
        ("Frases transcritas", sum(s["transcripciones"] for s in sesiones)),
    ]
    fila = _tabla(ws, fila, ["Indicador", "Valor"], [list(i) for i in indicadores], [34, 22])

    por_empleado: dict[str, dict] = {}
    for s in sesiones:
        e = por_empleado.setdefault(
            s["nombre"],
            {"sedes": set(), "modulos": set(), "sesiones": 0, "segundos": 0, "efectivos": 0, "almuerzo": 0, "break": 0,
             "lenguaje": 0, "expresion": 0, "ausencia": 0, "total": 0, "positivas": 0},
        )
        e["sedes"].add(s["sede"] or "—")
        e["modulos"].add(s["modulo"] or "—")
        e["sesiones"] += 1
        e["segundos"] += s["duracion_segundos"]
        e["efectivos"] += s["segundos_efectivos"]
        e["almuerzo"] += s["segundos_almuerzo"]
        e["break"] += s["segundos_break"]
        e["lenguaje"] += s["alertas_lenguaje"]
        e["expresion"] += s["alertas_expresion"]
        e["ausencia"] += s["alertas_ausencia"]
        e["total"] += s["total_alertas"]
        e["positivas"] += s["expresiones_positivas"]
    fila += 1
    ws.cell(row=fila, column=1, value="Resumen por empleado").font = Font(bold=True, size=12, color=_MORADO_OSCURO)
    _tabla(
        ws,
        fila + 1,
        ["Empleado", "Sede(s)", "Módulo(s)", "Sesiones", "Tiempo total", "Tiempo efectivo", "Almuerzo", "Break",
         "Lenguaje", "Expresión", "Ausencia", "Total alertas", "Positivas"],
        [
            [n, ", ".join(sorted(e["sedes"])), ", ".join(sorted(e["modulos"])), e["sesiones"], _duracion(e["segundos"]),
             _duracion(e["efectivos"]), _duracion(e["almuerzo"]), _duracion(e["break"]),
             e["lenguaje"], e["expresion"], e["ausencia"], e["total"], e["positivas"]]
            for n, e in sorted(por_empleado.items())
        ],
        [34, 22, 22, 10, 14, 14, 12, 12, 10, 10, 10, 12, 10],
        ajustar={2, 3},
    )
    ws.freeze_panes = None

    # ------------------------------------------------------------------ Sesiones
    ws = wb.create_sheet("Sesiones")
    ws.sheet_view.showGridLines = False
    fila = _titulo(ws, "Historial de sesiones — Sesiones", descripcion, 19)
    _tabla(
        ws,
        fila,
        ["Empleado", "Sede", "Módulo", "Fecha", "Hora inicio", "Fecha fin", "Hora fin", "Duración",
         "Almuerzos (veces)", "Tiempo total almuerzo", "Breaks (veces)", "Tiempo total break", "Tiempo efectivo",
         "Lenguaje", "Expresión", "Ausencia", "Total alertas", "Positivas", "Transcripciones"],
        [
            [s["nombre"], s["sede"] or "—", s["modulo"] or "—", _fecha(s["inicio"]), _hora(s["inicio"]),
             _fecha(s["fin"]) if s["fin"] else "En curso", _hora(s["fin"]) if s["fin"] else "En curso",
             _duracion(s["duracion_segundos"]), s["veces_almuerzo"], _duracion(s["segundos_almuerzo"]),
             s["veces_break"], _duracion(s["segundos_break"]), _duracion(s["segundos_efectivos"]),
             s["alertas_lenguaje"], s["alertas_expresion"], s["alertas_ausencia"],
             s["total_alertas"], s["expresiones_positivas"], s["transcripciones"]]
            for s in sesiones
        ],
        [28, 18, 18, 12, 11, 12, 11, 13, 11, 14, 11, 14, 14, 10, 10, 10, 12, 10, 15],
    )

    # ------------------------------------------------------------------ Pausas
    ws = wb.create_sheet("Pausas")
    ws.sheet_view.showGridLines = False
    fila = _titulo(ws, "Historial de sesiones — Almuerzos y breaks", descripcion, 9)
    pausas = sorted(((s, pz) for s in sesiones for pz in s.get("pausas", [])), key=lambda x: x[1]["inicio"])
    _tabla(
        ws,
        fila,
        ["Empleado", "Sede", "Módulo", "Inicio de la sesión", "Tipo", "Fecha", "Hora salida", "Hora regreso", "Duración"],
        [
            [s["nombre"], s["sede"] or "—", s["modulo"] or "—", _fecha_legible(s["inicio"]), _NOMBRE_PAUSA.get(pz["tipo"], pz["tipo"]),
             _fecha(pz["inicio"]), _hora(pz["inicio"]), _hora(pz["fin"]) if pz["fin"] else "En curso", _duracion(pz["segundos"])]
            for s, pz in pausas
        ],
        [26, 16, 16, 17, 12, 11, 12, 13, 13],
    )
    if not pausas:
        ws.cell(row=fila + 1, column=1, value="Sin almuerzos ni breaks en las sesiones exportadas.")

    # ------------------------------------------------------------------ Alertas
    ws = wb.create_sheet("Alertas")
    ws.sheet_view.showGridLines = False
    fila = _titulo(ws, "Historial de sesiones — Detalle de alertas", descripcion, 10)
    orden = sorted(alertas, key=lambda x: x[1]["timestamp"])
    inicio_datos = fila + 1
    _tabla(
        ws,
        fila,
        ["Empleado", "Sede", "Módulo", "Inicio de la sesión", "Fecha", "Hora", "Tipo", "Detalle", "Veredicto", "Foto"],
        [
            [s["nombre"], s["sede"] or "—", s["modulo"] or "—", _fecha_legible(s["inicio"]), _fecha(a["timestamp"]),
             _hora(a["timestamp"]), _NOMBRE_TIPO.get(a["tipo"], a["tipo"]), a["detalle"] or "",
             "—" if a["tipo"] == "expresion_positiva" else _NOMBRE_VEREDICTO.get(a["veredicto"], a["veredicto"]), ""]
            for s, a in orden
        ],
        [26, 16, 16, 17, 11, 10, 20, 55, 13, 11],
        ajustar={8},
    )
    for i, (_, a) in enumerate(orden):
        r = inicio_datos + i
        celda_veredicto = ws.cell(row=r, column=9)
        if a["veredicto"] == "confirmada" and a["tipo"] != "expresion_positiva":
            celda_veredicto.font = Font(bold=True, color=_ROJO)
        elif a["tipo"] == "expresion_positiva":
            ws.cell(row=r, column=7).font = Font(color=_VERDE, bold=True)
        imagen = _foto(a.get("captura_path"))
        if imagen is not None:
            ws.add_image(imagen, f"J{r}")
            ws.row_dimensions[r].height = 52
    if not orden:
        ws.cell(row=inicio_datos, column=1, value="Sin alertas en las sesiones exportadas.")

    # ------------------------------------------------------------------ Transcripciones
    ws = wb.create_sheet("Transcripciones")
    ws.sheet_view.showGridLines = False
    fila = _titulo(ws, "Historial de sesiones — Transcripciones", descripcion, 6)
    textos = sorted(((s, t) for s in sesiones for t in s.get("textos", [])), key=lambda x: x[1]["timestamp"])
    _tabla(
        ws,
        fila,
        ["Empleado", "Sede", "Módulo", "Fecha", "Hora", "Transcripción"],
        [[s["nombre"], s["sede"] or "—", s["modulo"] or "—", _fecha(t["timestamp"]), _hora(t["timestamp"]), t["texto"]] for s, t in textos],
        [26, 16, 16, 11, 10, 90],
        ajustar={6},
    )
    if not textos:
        ws.cell(row=fila + 1, column=1, value="Sin transcripciones en las sesiones exportadas.")

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
