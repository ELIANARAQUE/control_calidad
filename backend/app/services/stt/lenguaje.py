"""Deteccion de lenguaje inapropiado en el texto ya transcrito por Whisper.

El diccionario vive en Postgres (tabla `lenguaje_inapropiado`, editable desde el panel de
administrador en "Historial y Reportes"), con tres categorias:
  - groseria_fuerte: groserias/insultos inequivocos (se detectan en cualquier sensibilidad).
  - groseria_leve: insultos suaves ("idiota", "bobo"...): solo en sensibilidad "estricto".
  - mal_trato: frases que niegan la atencion o tratan mal al usuario, sin ser groserias
    ("no lo puedo ayudar", "averigue en otro lado"): se detectan siempre.

`DICCIONARIO_BASE` (abajo) es el diccionario inicial, con modismos de Colombia; se usa para
poblar la tabla (ver supabase_lenguaje.sql) y como respaldo si la base de datos no responde.

Comparacion: se normaliza el texto y cada termino igual (minusculas, sin tildes, "ñ" -> "n",
letras estiradas como "gonorreaaa" -> "gonorrea", signos -> espacios) y se busca el termino
como SECUENCIA DE PALABRAS COMPLETAS: "puta" no coincide dentro de "computadora", y las frases
de varias palabras ("hijo de puta", "no me pregunte eso") tambien funcionan.
"""
import logging
import re
import time
import unicodedata

logger = logging.getLogger(__name__)

CATEGORIAS = ("groseria_fuerte", "groseria_leve", "mal_trato")

DICCIONARIO_BASE: dict[str, list[str]] = {
    "groseria_fuerte": [
        # Colombia
        "hijueputa", "hijueputas", "hijueputica", "jueputa", "hp", "hpta", "hptas",
        "hijo de puta", "hijos de puta", "hija de puta", "hijuemadre",
        "gonorrea", "gonorreas", "gonorriento", "gonorrienta", "gonorrio",
        "malparido", "malparida", "malparidos", "malparidas", "malnacido", "malnacida",
        "carechimba", "careverga", "carepicha", "culicagado", "culicagada",
        "pirobo", "piroba", "pirobos",
        "me vale verga", "vale verga",
        # Generales en espanol
        "puta", "putas", "puto", "putos", "mierda", "mierdas", "comemierda", "come mierda",
        "verga", "vergas", "coño", "cabron", "cabrona", "cabrones", "culo", "culero",
        "zorra", "perra", "maricon", "maricona", "maricones",
        "chupamela", "chupala", "mamaguevo", "mamaguevos", "hijo de perra",
        "vete a la mierda", "vayase a la mierda", "que se joda", "jodase",
    ],
    "groseria_leve": [
        "marica", "maricas", "guevon", "guevona", "huevon", "huevona", "gueva", "guevas",
        "idiota", "idiotas", "imbecil", "imbeciles", "estupido", "estupida", "estupidos",
        "pendejo", "pendeja", "pendejos", "pendejada", "bobo", "boba", "bobos", "tarado", "tarada",
        "bruto", "bruta", "brutos", "baboso", "babosa", "lambon", "lambona",
        "chandoso", "chandosa", "ñero", "ñera", "gamin", "gamina", "mamon", "mamona",
        "maldito", "maldita", "malditos", "carajo", "joder", "jodido", "jodida", "no joda",
        "inutil", "inutiles", "incompetente", "ignorante",
    ],
    "mal_trato": [
        "no lo puedo ayudar", "no la puedo ayudar", "no los puedo ayudar",
        "no lo puedo ayudar con su solicitud", "no la puedo ayudar con su solicitud",
        "no puedo ayudarlo", "no puedo ayudarla", "no puedo hacer nada por usted",
        "no puedo hacer nada por ti", "averigue en otro lado", "averigue en otra parte",
        "vaya a averiguar en otro lado", "pregunte en otro lado", "busque a otro",
        "no me pregunte eso", "no me pregunte a mi", "eso no es conmigo",
        "eso no es mi problema", "no es mi problema", "ese no es mi problema", "no es mi trabajo",
        "no es asunto mio", "eso no me compete", "eso no me corresponde", "yo no tengo la culpa",
        "a mi que me importa", "no me interesa su problema",
        "arreglese como pueda", "arreglatelas como puedas", "hagale como quiera",
        "haga lo que quiera", "resuelva usted mismo", "resuelvalo usted",
        "no tengo tiempo para esto", "no tengo tiempo para usted", "deje de molestar",
        "no me moleste", "no vuelva a molestarme", "que fastidio con usted", "usted no entiende nada",
        "no le puedo dar esa informacion",
    ],
}


def normalizar(texto: str) -> str:
    """Minusculas, sin tildes ("ñ" -> "n"), letras repetidas 3+ veces reducidas a una
    ("gonorreaaa" -> "gonorrea") y todo lo que no sea letra convertido en espacio."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    solo_letras = re.sub(r"[^a-z]+", " ", sin_tildes)
    return re.sub(r"([a-z])\1{2,}", r"\1", solo_letras).strip()


def _terminos_normalizados(terminos: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    """(termino original, palabras normalizadas), mas largos primero: asi "hijo de puta" gana
    sobre "puta" y la alerta muestra la expresion completa."""
    pares = [(t, tuple(normalizar(t).split())) for t in terminos if normalizar(t)]
    return sorted(pares, key=lambda par: -len(par[1]))


class _Diccionario:
    """Cache en memoria del diccionario de Supabase, refrescada como maximo cada `_TTL` s."""

    _TTL = 60.0

    def __init__(self) -> None:
        self._por_categoria = {c: _terminos_normalizados(DICCIONARIO_BASE[c]) for c in CATEGORIAS}
        self._cargado_en = 0.0

    def reemplazar(self, filas: list[dict]) -> None:
        agrupado: dict[str, list[str]] = {c: [] for c in CATEGORIAS}
        for fila in filas:
            if fila.get("categoria") in agrupado:
                agrupado[fila["categoria"]].append(fila["termino"])
        if any(agrupado.values()):
            self._por_categoria = {c: _terminos_normalizados(agrupado[c]) for c in CATEGORIAS}
        self._cargado_en = time.monotonic()

    def vencido(self) -> bool:
        return (time.monotonic() - self._cargado_en) >= self._TTL

    def categoria(self, nombre: str) -> list[tuple[str, tuple[str, ...]]]:
        return self._por_categoria[nombre]


diccionario = _Diccionario()


async def refrescar_diccionario(forzar: bool = False) -> None:
    """Recarga el diccionario desde Supabase si la cache vencio. Si la base no responde, se
    sigue usando la ultima version (o `DICCIONARIO_BASE`): la deteccion nunca se apaga."""
    if not forzar and not diccionario.vencido():
        return
    from app.core.db import obtener_diccionario_lenguaje

    try:
        diccionario.reemplazar(await obtener_diccionario_lenguaje())
    except Exception:
        logger.exception("No se pudo cargar el diccionario de lenguaje desde Supabase; se usa el anterior")
        diccionario._cargado_en = time.monotonic()  # no reintentar en cada frase


def _buscar(palabras: tuple[str, ...], terminos: list[tuple[str, tuple[str, ...]]]) -> str | None:
    for original, secuencia in terminos:
        n = len(secuencia)
        for i in range(len(palabras) - n + 1):
            if palabras[i : i + n] == secuencia:
                return original
    return None


def contiene_lenguaje_inapropiado(texto: str, nivel: str = "estricto") -> tuple[str, str] | None:
    """Devuelve `(categoria, termino_detectado)` -categoria "mal trato" o "grosería"- o `None`
    si el texto esta limpio. `nivel` ("estricto"/"moderado") solo afecta a las groserias leves:
    las fuertes y el mal trato se detectan siempre."""
    palabras = tuple(normalizar(texto).split())
    if not palabras:
        return None

    # Prioridad cuando una frase tiene varias cosas: groseria fuerte > mal trato > groseria leve.
    encontrado = _buscar(palabras, diccionario.categoria("groseria_fuerte"))
    if encontrado:
        return "grosería", encontrado
    encontrado = _buscar(palabras, diccionario.categoria("mal_trato"))
    if encontrado:
        return "mal trato", encontrado
    if nivel != "moderado":
        encontrado = _buscar(palabras, diccionario.categoria("groseria_leve"))
        if encontrado:
            return "grosería", encontrado
    return None


# Compatibilidad con el endpoint de sensibilidad (moderado/estricto).
NIVELES_SENSIBILIDAD = {"estricto": "incluye groserias leves", "moderado": "solo groserias fuertes y mal trato"}
