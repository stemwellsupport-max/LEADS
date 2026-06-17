# app/main.py
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from .config import APP_NAME
from .dependencies import get_connection
from psycopg2.extras import RealDictCursor

app = FastAPI(title=APP_NAME, version="10.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Importar routers
from app.routers import auth, users, leads, agenda, google, health, webhooks, booked_calls, controles

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(leads.router)
app.include_router(agenda.router)
app.include_router(google.router)
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(booked_calls.router)
app.include_router(controles.router)

@app.get("/doctores")
def get_doctores(conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, email, telefono FROM usuarios WHERE rol='doctor' AND activo=true")
    doctores = cur.fetchall()
    cur.close()
    return {"usuarios": [dict(d) for d in doctores]}

@app.get("/asesores")
def get_asesores(conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, email, telefono FROM usuarios WHERE rol='asesor' AND activo=true")
    asesores = cur.fetchall()
    cur.close()
    return {"usuarios": [dict(a) for a in asesores]}

# Servir frontend
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="frontend")