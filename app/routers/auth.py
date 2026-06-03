from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import UsuarioLogin
import hashlib
from psycopg2.extras import RealDictCursor

router = APIRouter(tags=["Auth"])

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

@router.post("/login")
def login(data: UsuarioLogin, conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM usuarios WHERE email=%s AND password=%s AND activo=true",
                (data.email, hash_password(data.password)))
    user = cur.fetchone()
    cur.close()
    if not user:
        raise HTTPException(401, "Credenciales inválidas")
    return {"id": user["id"], "nombre": user["nombre"], "email": user["email"], "rol": user["rol"]}