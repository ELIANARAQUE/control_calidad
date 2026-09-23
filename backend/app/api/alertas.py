"""Endpoint para que el supervisor marque cada alerta como real o falsa alarma.

Estas etiquetas se guardan (ver app/core/db.py) para construir con el tiempo el dataset
que permitira entrenar un modelo temporal y dejar de depender solo de la heuristica.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.db import actualizar_veredicto

router = APIRouter()

VEREDICTOS_VALIDOS = {"confirmada", "falsa_alarma"}


class Veredicto(BaseModel):
    veredicto: str


@router.post("/alertas/{alerta_id}/veredicto")
async def marcar_veredicto(alerta_id: int, cuerpo: Veredicto) -> dict:
    if cuerpo.veredicto not in VEREDICTOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"veredicto debe ser uno de {VEREDICTOS_VALIDOS}")

    if not actualizar_veredicto(alerta_id, cuerpo.veredicto):
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    return {"alerta_id": alerta_id, "veredicto": cuerpo.veredicto}
