from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import UsuarioLogin
from ..services.auth_service import login_user

router = APIRouter(tags=["Auth"])

@router.post("/login")
def login(data: UsuarioLogin, conn = Depends(get_connection)):
    user = login_user(conn, data.email, data.password)
    if not user:
        raise HTTPException(401, "Credenciales inválidas")
    return user