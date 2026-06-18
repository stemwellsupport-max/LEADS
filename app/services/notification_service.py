# app/services/notification_service.py
# -*- coding: utf-8 -*-
"""
Servicio de notificaciones para Stemwell CRM.
"""
from datetime import datetime
from typing import List, Dict, Optional
from psycopg2.extras import RealDictCursor

# Tipos de notificación
NOTIF_LLAMADA_PENDIENTE = "llamada_pendiente"
NOTIF_CITA_VENCIDA_DOCTOR = "cita_vencida_doctor"
NOTIF_LEAD_DEVUELTO_ASESOR = "lead_devuelto_asesor"
NOTIF_TRATAMIENTO_CANCELADO = "tratamiento_cancelado"


def crear_notificacion(conn, lead_id, tipo, asunto, mensaje, usuario_id, lead_name=None):
    """Crea una notificación pendiente."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO notificaciones (lead_id, tipo, asunto, mensaje, fecha_envio, estado, usuario_id, lead_name)
        VALUES (%s, %s, %s, %s, NOW(), 'pendiente', %s, %s)
        RETURNING id
    """, (lead_id, tipo, asunto, mensaje, usuario_id, lead_name))
    nid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return nid


def resolver_notificacion(conn, notificacion_id, usuario_id):
    """Marca una notificación como resuelta."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones 
        SET estado = 'resuelta', resuelta_por = %s, fecha_resolucion = NOW()
        WHERE id = %s
    """, (usuario_id, notificacion_id))
    ok = cur.rowcount > 0
    conn.commit()
    cur.close()
    return ok


def resolver_todas(conn, usuario_id):
    """Resuelve todas las notificaciones pendientes de un usuario."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones 
        SET estado = 'resuelta', resuelta_por = %s, fecha_resolucion = NOW()
        WHERE usuario_id = %s AND estado = 'pendiente'
    """, (usuario_id, usuario_id))
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def listar_notificaciones(conn, usuario_id, solo_pendientes=True):
    """Lista notificaciones de un usuario."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    q = """
        SELECT n.id, n.lead_id, n.tipo, n.asunto, n.mensaje, n.fecha_envio, n.estado,
               n.usuario_id, n.lead_name
        FROM notificaciones n
        WHERE n.usuario_id = %s
    """
    if solo_pendientes:
        q += " AND n.estado = 'pendiente'"
    q += " ORDER BY n.fecha_envio DESC LIMIT 50"
    cur.execute(q, (usuario_id,))
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def contar_pendientes(conn, usuario_id):
    """Cuenta notificaciones pendientes de un usuario."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM notificaciones WHERE usuario_id = %s AND estado = 'pendiente'",
        (usuario_id,)
    )
    c = cur.fetchone()[0]
    cur.close()
    return c


def notificacion_existe(conn, lead_id, tipo, usuario_id):
    """Verifica si ya existe una notificación pendiente del mismo tipo."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM notificaciones 
        WHERE lead_id = %s AND tipo = %s AND usuario_id = %s AND estado = 'pendiente'
        LIMIT 1
    """, (lead_id, tipo, usuario_id))
    ex = cur.fetchone() is not None
    cur.close()
    return ex


# ══════════════════════════════════════════════════════════════
#  DETECCIÓN MASIVA
# ══════════════════════════════════════════════════════════════

def detectar_llamadas_pendientes(conn):
    """
    Encuentra booked_calls con fecha_llamada <= NOW() y estado = 'Pendiente'.
    Crea notificación para el asesor si no existe ya.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT bc.id, bc.lead_id, bc.asesor_id, bc.fecha_llamada, l.nombre
        FROM booked_calls bc
        JOIN leads l ON bc.lead_id = l.id
        WHERE bc.estado = 'Pendiente' 
          AND bc.fecha_llamada <= NOW()
    """)
    calls = cur.fetchall()
    cur.close()

    creadas = 0
    for c in calls:
        _, lead_id, asesor_id, fecha, nombre = c
        if not notificacion_existe(conn, lead_id, NOTIF_LLAMADA_PENDIENTE, asesor_id):
            hora = fecha.strftime("%H:%M") if fecha else ""
            crear_notificacion(
                conn, lead_id, NOTIF_LLAMADA_PENDIENTE,
                "📞 Callback pendiente",
                f"Debes llamar a {nombre} ahora. Agendada para las {hora}.",
                asesor_id, nombre
            )
            creadas += 1
    return creadas


def detectar_citas_vencidas_doctor(conn):
    """
    Encuentra citas en agenda_doctor con fecha_inicio < NOW() 
    cuyo lead sigue en sales_status de cita agendada.
    Notifica al doctor asignado del lead.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT ad.id, ad.lead_id, ad.doctor_id, ad.fecha_inicio, l.nombre
        FROM agenda_doctor ad
        JOIN leads l ON ad.lead_id = l.id
        WHERE ad.fecha_inicio <= NOW()
          AND l.sales_status IN ('Scheduled Appointment', 'Appointment Scheduled')
          AND l.doctor_id IS NOT NULL
    """)
    citas = cur.fetchall()
    cur.close()

    creadas = 0
    for c in citas:
        _, lead_id, doctor_id, fecha, nombre = c
        if not notificacion_existe(conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id):
            fstr = fecha.strftime("%d/%m/%Y %H:%M") if fecha else ""
            crear_notificacion(
                conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR,
                "⚠️ Cita vencida sin gestionar",
                f"{nombre} tuvo cita el {fstr} y sigue en 'Scheduled Appointment'. Actualiza el estado.",
                doctor_id, nombre
            )
            creadas += 1
    return creadas


def detectar_y_crear_notificaciones(conn):
    """Ejecuta todas las detecciones masivas."""
    t1 = detectar_llamadas_pendientes(conn)
    t2 = detectar_citas_vencidas_doctor(conn)
    return t1 + t2