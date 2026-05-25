from psycopg2.extras import RealDictCursor
from .auth_service import hash_password

def create_user(conn, data):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO usuarios (nombre,email,password,rol,telefono,idiomas) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
        (data.nombre, data.email, hash_password(data.password), data.rol,
         data.telefono, data.idiomas)
    )
    res = cur.fetchone()
    conn.commit()
    cur.close()
    return {"id": res[0]} if res else {"message": "Ya existe"}

def list_users(conn, rol: str = None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if rol:
        cur.execute(
            "SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true AND rol=%s",
            (rol,)
        )
    else:
        cur.execute(
            "SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true"
        )
    usuarios = cur.fetchall()
    cur.close()
    return {"usuarios": usuarios}

def change_password(conn, usuario_id: int, nueva_password: str):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, email FROM usuarios WHERE id=%s AND activo=true", (usuario_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        raise ValueError("Usuario no encontrado o inactivo")
    cur.execute(
        "UPDATE usuarios SET password=%s WHERE id=%s",
        (hash_password(nueva_password), usuario_id)
    )
    conn.commit()
    cur.close()
    return {"message": "Contraseña actualizada", "usuario_id": user["id"], "nombre": user["nombre"]}

def change_password_by_email(conn, email: str, nueva_password: str):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, email FROM usuarios WHERE email=%s AND activo=true", (email,))
    user = cur.fetchone()
    if not user:
        cur.close()
        raise ValueError("Usuario no encontrado o inactivo")
    cur.execute(
        "UPDATE usuarios SET password=%s WHERE email=%s",
        (hash_password(nueva_password), email)
    )
    conn.commit()
    cur.close()
    return {"message": "Contraseña actualizada", "usuario_id": user["id"], "nombre": user["nombre"]}