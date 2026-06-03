# app/dependencies.py
import psycopg2
from psycopg2 import pool
from .config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_CLIENT_ENCODING

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            client_encoding=DB_CLIENT_ENCODING
        )
    return _pool

def get_connection():
    pool_obj = get_pool()
    conn = pool_obj.getconn()
    try:
        yield conn
    finally:
        pool_obj.putconn(conn)