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
PALABRAS_INAPROPIADAS = {
    "mierda",
    "puta",
    "puto",
    "putos",
    "putas",
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
    "verga",
    "coño",
    "cono",
    "marica",
    "maricon",
    "gonorrea",
    "hijueputa",
    "hp",
}


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_tildes.lower()


def contiene_lenguaje_inapropiado(texto: str) -> str | None:
    """Devuelve la primera palabra inapropiada encontrada, o None si el texto esta limpio."""
    palabras = re.findall(r"[a-zñ]+", _normalizar(texto))
    for palabra in palabras:
        if palabra in PALABRAS_INAPROPIADAS:
            return palabra
    return None
