# app/routers/notificaciones.py
from fastapi import APIRouter, Query, HTTPException
from app.services.notification_service import (
    listar_notificaciones,
    contar_pendientes,
    resolver_notificacion,
    resolver_todas,
    detectar_y_crear_notificaciones
)
from app.dependencies import get_connection

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


@router.get("")
def obtener_notificaciones(
    usuario_id: int,
    solo_pendientes: bool = Query(True)
):
    """Lista notificaciones del usuario. Primero detecta nuevas."""
    conn = get_connection()
    try:
        detectar_y_crear_notificaciones(conn)
        notifs = listar_notificaciones(conn, usuario_id, solo_pendientes)
        pendientes = contar_pendientes(conn, usuario_id)
        return {"notificaciones": notifs, "pendientes": pendientes}
    finally:
        conn.close()


@router.put("/{notificacion_id}/resolver")
def resolver_una_notificacion(notificacion_id: int, data: dict):
    """Marca una notificación como resuelta. Body: {"usuario_id": 1}"""
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        raise HTTPException(400, "usuario_id es obligatorio")
    conn = get_connection()
    try:
        ok = resolver_notificacion(conn, notificacion_id, usuario_id)
        pendientes = contar_pendientes(conn, usuario_id)
        return {"ok": ok, "pendientes": pendientes}
    finally:
        conn.close()


@router.put("/resolver-todas")
def resolver_todas_notificaciones(data: dict):
    """Resuelve todas las notificaciones pendientes. Body: {"usuario_id": 1}"""
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        raise HTTPException(400, "usuario_id es obligatorio")
    conn = get_connection()
    try:
        resueltas = resolver_todas(conn, usuario_id)
        return {"resueltas": resueltas, "pendientes": 0}
    finally:
        conn.close()