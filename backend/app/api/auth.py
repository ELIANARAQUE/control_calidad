from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import cerrar_sesion, iniciar_sesion, requerir_admin

router = APIRouter()


class Credenciales(BaseModel):
    usuario: str
    clave: str


@router.post("/auth/login")
async def login(cuerpo: Credenciales) -> dict:
    token = iniciar_sesion(cuerpo.usuario, cuerpo.clave)
    return {"token": token}


@router.post("/auth/logout")
async def logout(token: str = Depends(requerir_admin)) -> dict:
    cerrar_sesion(token)
    return {"ok": True}
