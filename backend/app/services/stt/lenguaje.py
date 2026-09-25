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

# Frases (no palabras sueltas) que indican mal trato o negacion de ayuda al usuario: el
# empleado no dijo ninguna grosería, pero igual dejo a la persona sin la atencion que vino a
# buscar, o la trato de forma cortante/despectiva. Se detectan por coincidencia de subcadena
# sobre el texto normalizado (sin tildes/minusculas), no por palabra completa, porque son
# expresiones de varias palabras. Se activan siempre (no dependen de la sensibilidad de
# lenguaje moderado/estricto, que es solo para groserias).
FRASES_MALTRATO = {
    "no lo puedo ayudar con eso",
    "no lo puedo ayudar con su solicitud",
    "no la puedo ayudar con eso",
    "no la puedo ayudar con su solicitud",
    "no puedo ayudarlo",
    "no puedo ayudarla",
    "no puedo hacer nada por usted",
    "no puedo hacer nada por ti",
    "averigue en otro lado",
    "averigue en otra parte",
    "vaya a averiguar en otro lado",
    "eso no es mi problema",
    "no es mi problema",
    "no es mi trabajo",
    "eso no me compete",
    "eso no me corresponde",
    "yo no tengo la culpa",
    "arreglese como pueda",
    "arreglatelas como puedas",
    "no me importa lo que le pase",
    "no me interesa su problema",
    "resuelva usted mismo",
    "resuelvalo usted",
    "no tengo tiempo para esto",
    "ese no es mi problema",
    "no vuelva a molestarme",
    "no le puedo dar esa informacion asi de facil",
}


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_tildes.lower()


def contiene_lenguaje_inapropiado(texto: str, nivel: str = "estricto") -> tuple[str, str] | None:
    """Devuelve `(categoria, texto_detectado)` si el texto contiene una grosería o una frase
    de mal trato/negacion de ayuda, o `None` si esta limpio.

    `categoria` es `"grosería"` o `"mal trato"`. `nivel` ("estricto"/"moderado") solo afecta
    la lista de groserias, ajustable en caliente por el supervisor; las frases de mal trato
    se revisan siempre, sin importar la sensibilidad configurada.
    """
    texto_normalizado = _normalizar(texto)

    for frase in FRASES_MALTRATO:
        if frase in texto_normalizado:
            return "mal trato", frase

    lista = NIVELES_SENSIBILIDAD.get(nivel, PALABRAS_ESTRICTO)
    palabras = re.findall(r"[a-zñ]+", texto_normalizado)
    for palabra in palabras:
        if palabra in lista:
            return "grosería", palabra
    return None
