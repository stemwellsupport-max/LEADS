from fastapi import Depends
from .database import get_db

def get_connection():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()