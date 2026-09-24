"""Deteccion de lenguaje inapropiado en el texto ya transcrito por Whisper.

Heuristica simple por lista de palabras (no requiere modelo adicional ni GPU extra):
suficiente para marcar candidatos y que el supervisor confirme/descarte, igual que con
las alertas de postura. Si el volumen de falsos positivos/negativos lo justifica mas
adelante, esto se puede reemplazar por un clasificador de toxicidad en espaniol.
"""
import re
import unicodedata

# Lista base de groserias/insultos comunes en espaniol. Se compara sin tildes y en
# minusculas, y por palabra completa (no substring) para evitar falsos positivos como
# "clasificar" conteniendo "asic...". Ajustar segun el contexto/región de la operación.
# Subconjunto de groserias fuertes/inequivocas: es lo unico que dispara alerta en nivel
# "moderado". El resto (insultos suaves tipo "idiota") solo se marca en nivel "estricto".
PALABRAS_MODERADO = {
    "mierda",
    "puta",
    "puto",
    "putos",
    "putas",
    "gonorrea",
    "hijueputa",
    "hijuemadre",
    "hp",
    "malparido",
    "malparida",
    "verga",
    "coño",
    "cono",
}

PALABRAS_ESTRICTO = PALABRAS_MODERADO | {
    # Groserias generales en espaniol
    "pendejo",
    "pendeja",
    "pendejada",
    "cabron",
    "cabrona",
    "idiota",
    "imbecil",
    "estupido",
    "estupida",
    "maldito",
    "maldita",
    "joder",
    "carajo",
    "marica",
    "maricon",
    # Modismos/groserias tipicas de Colombia (se dejan fuera a proposito palabras ambiguas
    # como "chimba" o "arrecho", que en Colombia se usan tanto en sentido positivo como
    # ofensivo segun el contexto/tono - meterlas aqui dispararia muchos falsos positivos)
    "guevon",
    "gueva",
    "gonorrio",
    "chandoso",
    "chandosa",
}

NIVELES_SENSIBILIDAD = {"estricto": PALABRAS_ESTRICTO, "moderado": PALABRAS_MODERADO}


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_tildes.lower()


def contiene_lenguaje_inapropiado(texto: str, nivel: str = "estricto") -> str | None:
    """Devuelve la primera palabra inapropiada encontrada, o None si el texto esta limpio.

    `nivel`: "estricto" (lista completa) o "moderado" (solo groserias fuertes e inequivocas),
    ajustable en caliente por el supervisor desde el panel de control.
    """
    lista = NIVELES_SENSIBILIDAD.get(nivel, PALABRAS_ESTRICTO)
    palabras = re.findall(r"[a-zñ]+", _normalizar(texto))
    for palabra in palabras:
        if palabra in lista:
            return palabra
    return None
