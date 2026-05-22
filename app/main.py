from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import auth, users, leads, agenda, controles, google, health
from .config import APP_NAME
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI(title=APP_NAME, version="7.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(leads.router)
app.include_router(agenda.router)
app.include_router(controles.router)
app.include_router(google.router)
app.include_router(health.router)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="frontend")
