"""Endpoint para que el supervisor marque cada alerta como real o falsa alarma.

Estas etiquetas se guardan (ver app/core/db.py) para construir con el tiempo el dataset
que permitira entrenar un modelo temporal y dejar de depender solo de la heuristica.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.auth import requerir_admin
from app.core.seguridad import descifrar_bytes
from app.core.db import RUTA_CAPTURAS, actualizar_veredicto, eliminar_alerta_positiva, obtener_captura_path

router = APIRouter()

VEREDICTOS_VALIDOS = {"confirmada", "falsa_alarma"}


@router.get("/alertas/{alerta_id}/captura.jpg")
async def captura_alerta(alerta_id: int, _admin: str = Depends(requerir_admin)) -> Response:
    """Foto guardada automaticamente en el momento en que se disparo la alerta (postura,
    expresion o lenguaje), para que el supervisor pueda ver que la origino sin depender de
    haber estado mirando la transmision en vivo justo en ese instante."""
    ruta_relativa = await obtener_captura_path(alerta_id)
    if not ruta_relativa:
        raise HTTPException(status_code=404, detail="Esta alerta no tiene una captura asociada")

    ruta_absoluta = (RUTA_CAPTURAS / ruta_relativa).resolve()
    if RUTA_CAPTURAS.resolve() not in ruta_absoluta.parents or not ruta_absoluta.is_file():
        raise HTTPException(status_code=404, detail="Captura no encontrada")

    return Response(content=descifrar_bytes(ruta_absoluta.read_bytes()), media_type="image/jpeg")


@router.delete("/alertas/{alerta_id}")
async def eliminar_alerta(alerta_id: int, _admin: str = Depends(requerir_admin)) -> dict:
    """Solo para expresiones positivas (no se califican, solo se eliminan)."""
    eliminada, captura_path = await eliminar_alerta_positiva(alerta_id)
    if not eliminada:
        raise HTTPException(status_code=404, detail="Solo se pueden eliminar expresiones positivas")
    if captura_path:
        (RUTA_CAPTURAS / captura_path).unlink(missing_ok=True)
    return {"alerta_id": alerta_id, "eliminada": True}


class Veredicto(BaseModel):
    veredicto: str


@router.post("/alertas/{alerta_id}/veredicto")
async def marcar_veredicto(alerta_id: int, cuerpo: Veredicto, _admin: str = Depends(requerir_admin)) -> dict:
    if cuerpo.veredicto not in VEREDICTOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"veredicto debe ser uno de {VEREDICTOS_VALIDOS}")

    if not await actualizar_veredicto(alerta_id, cuerpo.veredicto):
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    return {"alerta_id": alerta_id, "veredicto": cuerpo.veredicto}
