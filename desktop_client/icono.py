"""Genera en memoria el icono de la bandeja del sistema (evita depender de un .ico externo).

Diseño minimal: circulo solido de un solo color, coherente con el acento del frontend
(#1f5f4f), sin degradados ni efectos — el mismo lenguaje visual que el resto de la app.
"""
from PIL import Image, ImageDraw

ACENTO = (31, 95, 79)  # mismo verde --acento usado en frontend/employee/style.css


def crear_icono(tamano: int = 64) -> Image.Image:
    img = Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margen = tamano // 8
    draw.ellipse([margen, margen, tamano - margen, tamano - margen], fill=ACENTO)
    return img
