import hashlib
from psycopg2.extras import RealDictCursor

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def login_user(conn, email: str, password: str):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM usuarios WHERE email=%s AND password=%s AND activo=true",
        (email, hash_password(password))
    )
    user = cur.fetchone()
    cur.close()
    if not user:
        return None
    return {
        "id": user["id"],
        "nombre": user["nombre"],
        "email": user["email"],
        "rol": user["rol"]
    }