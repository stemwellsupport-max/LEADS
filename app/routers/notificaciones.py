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
    resolver_notificaciones_por_tipo,
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


# Tipos de notificaciones que deben eliminarse en cascada
TIPOS_RELACIONADOS = {
    'cita_no_show': [
        'cita_no_show', 'cita_cancelada', 'cita_vencida_doctor',
        'tratamiento_cancelado', 'lead_devuelto_asesor'
    ],
    'cita_cancelada': [
        'cita_no_show', 'cita_cancelada', 'cita_vencida_doctor',
        'tratamiento_cancelado', 'lead_devuelto_asesor'
    ],
    'tratamiento_cancelado': [
        'tratamiento_cancelado', 'cita_cancelada', 'cita_no_show',
        'lead_devuelto_asesor'
    ],
    'lead_devuelto_asesor': [
        'lead_devuelto_asesor', 'cita_no_show', 'cita_cancelada',
        'tratamiento_cancelado'
    ],
    'cita_vencida_doctor': [
        'cita_vencida_doctor', 'cita_no_show', 'cita_cancelada'
    ],
    'pending_evaluation_vencida': [
        'pending_evaluation_vencida', 'cita_vencida_doctor'
    ],
    'treatment_proposal_sin_respuesta': [
        'treatment_proposal_sin_respuesta'
    ],
    'treatment_confirmed_pendiente': [
        'treatment_confirmed_pendiente'
    ],
    'callback_pendiente': [
        'callback_pendiente', 'llamada_pendiente'
    ],
    'llamada_pendiente': [
        'callback_pendiente', 'llamada_pendiente'
    ],
}


from datetime import datetime, timedelta

_ULTIMA_DETECCION = None

@router.get("")
def obtener_notificaciones(usuario_id: int, solo_pendientes: bool = Query(True)):
    global _ULTIMA_DETECCION
    
    conn = _get_conn()
    try:
        ahora = datetime.now()
        
        # Solo detectar cada 5 minutos
        if _ULTIMA_DETECCION is None or (ahora - _ULTIMA_DETECCION) > timedelta(minutes=5):
            detectar_y_crear_notificaciones(conn)
            _ULTIMA_DETECCION = ahora
        
        notifs = listar_notificaciones(conn, usuario_id, solo_pendientes)
        pendientes = contar_pendientes(conn, usuario_id)
        return {"notificaciones": notifs, "pendientes": pendientes, "nuevas_creadas": 0}
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")
    finally:
        conn.close()


@router.put("/{notificacion_id}/resolver")
def resolver_una_notificacion(notificacion_id: int, data: dict):
    """
    Elimina una notificación y sus relacionadas del mismo lead.
    """
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        raise HTTPException(400, "usuario_id es obligatorio")
    
    conn = _get_conn()
    try:
        # Obtener info de la notificación antes de eliminarla
        cur = conn.cursor()
        cur.execute(
            "SELECT lead_id, tipo FROM notificaciones WHERE id=%s AND usuario_id=%s",
            (notificacion_id, usuario_id)
        )
        row = cur.fetchone()
        cur.close()
        
        if not row:
            raise HTTPException(404, "Notificación no encontrada")
        
        lead_id, tipo = row[0], row[1]
        
        # Eliminar la notificación específica
        ok = resolver_notificacion(conn, notificacion_id, usuario_id)
        
        # Eliminar notificaciones relacionadas del mismo lead
        eliminadas_extra = 0
        if tipo in TIPOS_RELACIONADOS:
            eliminadas_extra = resolver_notificaciones_por_tipo(
                conn, lead_id, TIPOS_RELACIONADOS[tipo]
            )
        
        if not ok:
            raise HTTPException(404, "No encontrada")
        
        pendientes = contar_pendientes(conn, usuario_id)
        return {
            "ok": True,
            "pendientes": pendientes,
            "eliminadas": 1 + eliminadas_extra,
            "lead_id": lead_id
        }
    finally:
        conn.close()


@router.put("/resolver-todas")
def resolver_todas_notificaciones(data: dict):
    """Elimina todas las notificaciones pendientes de un usuario."""
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        raise HTTPException(400, "usuario_id es obligatorio")
    
    conn = _get_conn()
    try:
        resueltas = resolver_todas(conn, usuario_id)
        return {
            "resueltas": resueltas,
            "pendientes": 0
        }
    finally:
        conn.close()


@router.get("/diagnostico")
def diagnosticar():
    """Endpoint de diagnóstico."""
    conn = _get_conn()
    try:
        return {
            "estado": "completado",
            "diagnostico": diagnosticar_asignaciones(conn)
        }
    finally:
        conn.close()


@router.post("/forzar-deteccion")
def forzar_deteccion():
    """Fuerza la detección masiva de notificaciones."""
    conn = _get_conn()
    try:
        nuevas = detectar_y_crear_notificaciones(conn)
        return {
            "estado": "completado",
            "nuevas_notificaciones": nuevas
        }
    finally:
        conn.close()