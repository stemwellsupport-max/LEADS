# app/routers/notificaciones.py
# -*- coding: utf-8 -*-
"""
Router de notificaciones para Stemwell CRM.
"""
from fastapi import APIRouter, Query, HTTPException
from app.services.notification_service import (
    listar_notificaciones,
    contar_pendientes,
    resolver_notificacion,
    resolver_todas,
    detectar_y_crear_notificaciones,
    diagnosticar_asignaciones
)
import psycopg2
import os

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


def _get_conn():
    """Obtiene una conexión directa a la BD usando variables de entorno"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", 5432),
        database=os.getenv("DB_NAME", "stemwell"),
        user=os.getenv("DB_USER", "crm_user"),
        password=os.getenv("DB_PASSWORD", "crm2024"),
        client_encoding="UTF8"
    )


@router.get("")
def obtener_notificaciones(usuario_id: int, solo_pendientes: bool = Query(True)):
    """Lista notificaciones del usuario."""
    conn = _get_conn()
    try:
        nuevas = detectar_y_crear_notificaciones(conn)
        notifs = listar_notificaciones(conn, usuario_id, solo_pendientes)
        pendientes = contar_pendientes(conn, usuario_id)
        return {"notificaciones": notifs, "pendientes": pendientes, "nuevas_creadas": nuevas}
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")
    finally:
        conn.close()


@router.put("/{notificacion_id}/resolver")
def resolver_una_notificacion(notificacion_id: int, data: dict):
    """Marca una notificación como resuelta."""
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        raise HTTPException(400, "usuario_id es obligatorio")
    conn = _get_conn()
    try:
        ok = resolver_notificacion(conn, notificacion_id, usuario_id)
        if not ok:
            raise HTTPException(404, "No encontrada")
        return {"ok": True, "pendientes": contar_pendientes(conn, usuario_id)}
    finally:
        conn.close()


@router.put("/resolver-todas")
def resolver_todas_notificaciones(data: dict):
    """Resuelve todas las notificaciones pendientes de un usuario."""
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        raise HTTPException(400, "usuario_id es obligatorio")
    conn = _get_conn()
    try:
        resueltas = resolver_todas(conn, usuario_id)
        return {"resueltas": resueltas, "pendientes": 0}
    finally:
        conn.close()


@router.get("/diagnostico")
def diagnosticar():
    """Endpoint de diagnóstico."""
    conn = _get_conn()
    try:
        return {"estado": "completado", "diagnostico": diagnosticar_asignaciones(conn)}
    finally:
        conn.close()


@router.post("/forzar-deteccion")
def forzar_deteccion():
    """Fuerza la detección masiva de notificaciones."""
    conn = _get_conn()
    try:
        nuevas = detectar_y_crear_notificaciones(conn)
        return {"estado": "completado", "nuevas_notificaciones": nuevas}
    finally:
        conn.close()