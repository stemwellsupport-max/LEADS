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
    """Lista notificaciones de un usuario. Retorna lista de dicts."""
    cur = conn.cursor()
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
    cols = ["id", "lead_id", "tipo", "asunto", "mensaje", "fecha_envio", "estado", "usuario_id", "lead_name"]
    resultado = []
    for row in rows:
        d = {}
        for i, col in enumerate(cols):
            val = row[i]
            if isinstance(val, datetime):
                val = val.isoformat()
            d[col] = val
        resultado.append(d)
    cur.close()
    return resultado


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
#  AUTO-LIMPIEZA DE NOTIFICACIONES HUÉRFANAS
# ══════════════════════════════════════════════════════════════

def limpiar_notificaciones_huerfanas(conn):
    """
    Resuelve automáticamente notificaciones que ya no aplican:
    
    1. llamada_pendiente → Si el booked_call ya no está Pendiente o fecha futura
    2. cita_vencida_doctor → Si el lead ya no está en 'Scheduled Appointment'
    3. tratamiento_cancelado → Si el appointment_status ya no es 'Canceled'
    4. lead_devuelto_asesor → Si el medical_status ya no es 'Candidate Rejected'
    
    También elimina duplicados (conserva el más reciente).
    """
    total_resueltas = 0
    
    # 1. Resolver llamadas pendientes que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM booked_calls bc
        WHERE n.lead_id = bc.lead_id
          AND n.tipo = 'llamada_pendiente'
          AND n.estado = 'pendiente'
          AND (
              bc.estado != 'Pendiente' 
              OR bc.fecha_llamada > NOW()
          )
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 2. Resolver citas vencidas que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'cita_vencida_doctor'
          AND n.estado = 'pendiente'
          AND l.sales_status NOT IN ('Scheduled Appointment', 'Appointment Scheduled')
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 3. Resolver tratamientos cancelados que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'tratamiento_cancelado'
          AND n.estado = 'pendiente'
          AND l.appointment_status != 'Canceled'
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 4. Resolver leads devueltos que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'lead_devuelto_asesor'
          AND n.estado = 'pendiente'
          AND l.medical_status != 'Candidate Rejected'
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 5. Eliminar duplicados (conserva el más reciente)
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM notificaciones a
        USING notificaciones b
        WHERE a.lead_id = b.lead_id
          AND a.tipo = b.tipo
          AND a.usuario_id = b.usuario_id
          AND a.estado = 'pendiente'
          AND b.estado = 'pendiente'
          AND a.fecha_envio < b.fecha_envio
    """)
    duplicados = cur.rowcount
    conn.commit()
    cur.close()
    
    if total_resueltas > 0 or duplicados > 0:
        print(f"🧹 Auto-limpieza: {total_resueltas} notificaciones resueltas, {duplicados} duplicados eliminados")
    
    return total_resueltas + duplicados


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
        if asesor_id is not None:
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
        if doctor_id is not None:
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


def detectar_leads_devueltos_asesor(conn):
    """
    Detecta leads cuyo medical_status fue cambiado a 'Candidate Rejected'
    y notifica al asesor asignado para que haga seguimiento.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id
        FROM leads l
        WHERE l.medical_status = 'Candidate Rejected'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id = l
        if asesor_id is not None:
            if not notificacion_existe(conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR, asesor_id):
                crear_notificacion(
                    conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR,
                    "🔄 Lead devuelto por el doctor",
                    f"{nombre} fue rechazado como candidato. Contacta al paciente para dar seguimiento.",
                    asesor_id, nombre
                )
                creadas += 1
    return creadas


def detectar_tratamientos_cancelados(conn):
    """
    Detecta leads cuyo appointment_status cambió a 'Canceled' recientemente
    y notifica al asesor asignado.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id
        FROM leads l
        WHERE l.appointment_status = 'Canceled'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id = l
        if asesor_id is not None:
            if not notificacion_existe(conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO, asesor_id):
                crear_notificacion(
                    conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO,
                    "❌ Cita cancelada",
                    f"La cita de {nombre} fue cancelada. Revisa el caso y contacta al paciente.",
                    asesor_id, nombre
                )
                creadas += 1
    return creadas


def detectar_y_crear_notificaciones(conn):
    """
    Ejecuta primero la limpieza automática y luego todas las detecciones masivas.
    """
    # 1. PRIMERO LIMPIAR notificaciones que ya no aplican
    limpiar_notificaciones_huerfanas(conn)
    
    # 2. LUEGO detectar nuevas notificaciones
    t1 = detectar_llamadas_pendientes(conn)
    t2 = detectar_citas_vencidas_doctor(conn)
    t3 = detectar_leads_devueltos_asesor(conn)
    t4 = detectar_tratamientos_cancelados(conn)
    
    return t1 + t2 + t3 + t4