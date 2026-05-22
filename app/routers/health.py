from fastapi import APIRouter
from ..database import get_db

router = APIRouter(tags=["Health"])

@router.get("/health")
def health():
    try:
        conn = get_db()
        conn.close()
        return {"status": "ok"}
    except:
        return {"status": "error"}