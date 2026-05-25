from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import UsuarioCreate
from ..services.user_service import create_user, list_users

router = APIRouter(tags=["Usuarios"])

@router.post("/usuarios")
def crear_usuario(data: UsuarioCreate, conn = Depends(get_connection)):
    result = create_user(conn, data)
    if "message" in result and result["message"] == "Ya existe":
        return result
    return result

@router.get("/usuarios")
def listar_usuarios(rol: str = None, conn = Depends(get_connection)):
    return list_users(conn, rol)

@router.get("/doctores")
def listar_doctores(conn = Depends(get_connection)):
    return list_users(conn, rol="doctor")

@router.get("/asesores")
def listar_asesores(conn = Depends(get_connection)):
    return list_users(conn, rol="asesor")

from pydantic import BaseModel
from ..services.user_service import create_user, list_users, change_password, change_password_by_email

class CambiarPassword(BaseModel):
    nueva_password: str

class CambiarPasswordPorEmail(BaseModel):
    email: str
    nueva_password: str

@router.put("/usuarios/{usuario_id}/password")
def cambiar_password(usuario_id: int, data: CambiarPassword, conn = Depends(get_connection)):
    try:
        return change_password(conn, usuario_id, data.nueva_password)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/usuarios/password/por-email")
def cambiar_password_por_email(data: CambiarPasswordPorEmail, conn = Depends(get_connection)):
    try:
        return change_password_by_email(conn, data.email, data.nueva_password)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))