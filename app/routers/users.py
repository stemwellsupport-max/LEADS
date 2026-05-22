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