from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import UsuarioCreate
import hashlib
from psycopg2.extras import RealDictCursor
from typing import Optional

router = APIRouter(prefix="/usuarios", tags=["Users"])

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

@router.post("")
def crear_usuario(data: UsuarioCreate, conn=Depends(get_connection)):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO usuarios (nombre,email,password,rol,telefono,idiomas) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
        (data.nombre, data.email, hash_password(data.password), data.rol, data.telefono, data.idiomas)
    )
    res = cur.fetchone()
    conn.commit()
    cur.close()
    if not res:
        raise HTTPException(400, "El email ya existe")
    return {"id": res[0]}

@router.get("")
def listar_usuarios(rol: Optional[str] = None, conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if rol:
        cur.execute("SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true AND rol=%s", (rol,))
    else:
        cur.execute("SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true")
    usuarios = cur.fetchall()
    cur.close()
    return {"usuarios": usuarios}

@router.get("/doctores")
def listar_doctores(conn=Depends(get_connection)):
    return listar_usuarios(rol="doctor", conn=conn)

@router.get("/asesores")
def listar_asesores(conn=Depends(get_connection)):
    return listar_usuarios(rol="asesor", conn=conn)

@router.put("/{usuario_id}/password")
def cambiar_password(usuario_id: int, data: dict, conn=Depends(get_connection)):
    nueva = data.get("nueva_password", "")
    if len(nueva) < 6:
        raise HTTPException(400, "Contraseña mínimo 6 caracteres")
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET password=%s WHERE id=%s", (hash_password(nueva), usuario_id))
    conn.commit()
    cur.close()
    return {"message": "Contraseña actualizada"}