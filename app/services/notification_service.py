# app/services/notification_service.py
# -*- coding: utf-8 -*-
"""
Servicio de notificaciones para Stemwell CRM.
Versión completa con todas las reglas de negocio.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# ══════════════════════════════════════════════════════════════
#  TIPOS DE NOTIFICACIÓN
# ══════════════════════════════════════════════════════════════

# Para Doctores
NOTIF_PENDING_EVALUATION_VENCIDA = "pending_evaluation_vencida"
NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA = "treatment_proposal_sin_respuesta"
NOTIF_CITA_VENCIDA_DOCTOR = "cita_vencida_doctor"

# Para Asesores
NOTIF_CITA_NO_SHOW = "cita_no_show"
NOTIF_CITA_CANCELADA = "cita_cancelada"
NOTIF_TREATMENT_CONFIRMED_PENDIENTE = "treatment_confirmed_pendiente"
NOTIF_CALLBACK_PENDIENTE = "callback_pendiente"
NOTIF_LLAMADA_PENDIENTE = "llamada_pendiente"
NOTIF_LEAD_DEVUELTO_ASESOR = "lead_devuelto_asesor"
NOTIF_TRATAMIENTO_CANCELADO = "tratamiento_cancelado"


# ══════════════════════════════════════════════════════════════
#  FUNCIONES BÁSICAS DE NOTIFICACIONES
# ══════════════════════════════════════════════════════════════

def crear_notificacion(conn, lead_id, tipo, asunto, mensaje, usuario_id, lead_name=None):
    """
    Crea una notificación pendiente.
    Retorna el ID de la notificación creada o None si no se pudo crear.
    """
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO notificaciones (lead_id, tipo, asunto, mensaje, fecha_envio, estado, usuario_id, lead_name)
            VALUES (%s, %s, %s, %s, NOW(), 'pendiente', %s, %s)
            RETURNING id
        """, (lead_id, tipo, asunto, mensaje, usuario_id, lead_name))
        nid = cur.fetchone()[0]
        conn.commit()
        return nid
    except Exception as e:
        print(f"❌ Error creando notificación: {e}")
        conn.rollback()
        return None
    finally:
        cur.close()


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
    q += " ORDER BY n.fecha_envio DESC LIMIT 200"
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
    """Verifica si ya existe una notificación pendiente del mismo tipo para el mismo usuario."""
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
    Resuelve automáticamente notificaciones que ya no aplican
    porque el lead cambió de estado.
    """
    total_resueltas = 0
    cur = conn.cursor()

    # 1. Pending Evaluation vencida → resolver si ya no está en Pending Evaluation
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'pending_evaluation_vencida'
          AND n.estado = 'pendiente'
          AND l.medical_status != 'Pending Evaluation'
    """)
    total_resueltas += cur.rowcount

    # 2. Treatment Proposal sin respuesta → resolver si ya no está en ese estado
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'treatment_proposal_sin_respuesta'
          AND n.estado = 'pendiente'
          AND l.medical_status != 'Treatment Proposal Sent'
    """)
    total_resueltas += cur.rowcount

    # 3. Cita vencida doctor → resolver si ya no está en Scheduled Appointment
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'cita_vencida_doctor'
          AND n.estado = 'pendiente'
          AND l.sales_status NOT IN ('Scheduled Appointment', 'Appointment Scheduled')
    """)
    total_resueltas += cur.rowcount

    # 4. No Show → resolver si ya no está en No Show
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'cita_no_show'
          AND n.estado = 'pendiente'
          AND l.appointment_status != 'No Show'
    """)
    total_resueltas += cur.rowcount

    # 5. Cita cancelada → resolver si ya no está cancelada
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'cita_cancelada'
          AND n.estado = 'pendiente'
          AND l.appointment_status != 'Canceled'
    """)
    total_resueltas += cur.rowcount

    # 6. Treatment Confirmed pendiente → resolver si ya cambió
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'treatment_confirmed_pendiente'
          AND n.estado = 'pendiente'
          AND l.sales_status != 'Treatment Confirmed'
    """)
    total_resueltas += cur.rowcount

    # 7. Callbacks → resolver si ya pasaron o cambiaron de estado
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM booked_calls bc
        WHERE n.lead_id = bc.lead_id
          AND n.tipo IN ('callback_pendiente', 'llamada_pendiente')
          AND n.estado = 'pendiente'
          AND (bc.estado != 'Pendiente' OR bc.fecha_llamada > NOW())
    """)
    total_resueltas += cur.rowcount

    # 8. Tratamiento cancelado → resolver si ya no está cancelado
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'tratamiento_cancelado'
          AND n.estado = 'pendiente'
          AND l.appointment_status != 'Canceled'
    """)
    total_resueltas += cur.rowcount

    # 9. Lead devuelto asesor → resolver si ya no está Candidate Rejected
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', resuelta_por = n.usuario_id, fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'lead_devuelto_asesor'
          AND n.estado = 'pendiente'
          AND l.medical_status != 'Candidate Rejected'
    """)
    total_resueltas += cur.rowcount

    # 10. Eliminar duplicados (conserva el más reciente)
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
        print(f"🧹 Auto-limpieza: {total_resueltas} notif resueltas, {duplicados} duplicados eliminados")

    return total_resueltas + duplicados


# ══════════════════════════════════════════════════════════════
#  DETECCIÓN PARA DOCTORES
# ══════════════════════════════════════════════════════════════

def detectar_pending_evaluation_vencidas(conn):
    """
    Detecta leads en 'Pending Evaluation' cuya fecha de consulta (treatment_date)
    ya pasó y no se ha actualizado el estado.
    Notifica al doctor asignado.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.doctor_id, l.treatment_date
        FROM leads l
        WHERE l.medical_status = 'Pending Evaluation'
          AND l.doctor_id IS NOT NULL
          AND l.treatment_date IS NOT NULL
          AND l.treatment_date <= NOW()
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, doctor_id, treatment_date = l
        fecha_str = treatment_date.strftime("%d/%m/%Y %H:%M") if treatment_date else "fecha no especificada"

        if not notificacion_existe(conn, lead_id, NOTIF_PENDING_EVALUATION_VENCIDA, doctor_id):
            nid = crear_notificacion(
                conn, lead_id, NOTIF_PENDING_EVALUATION_VENCIDA,
                "🩺 Consulta pendiente de actualización",
                f"⚠️ {nombre} tuvo consulta el {fecha_str} y sigue en 'Pending Evaluation'. Debes actualizar el estado médico del paciente.",
                doctor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [DOCTOR] Pending Evaluation vencidas: {creadas} notificaciones")
    return creadas


def detectar_treatment_proposal_sin_respuesta(conn):
    """
    Detecta leads en 'Treatment Proposal Sent' por más de 7 días sin cambio.
    Notifica al doctor asignado.
    """
    cur = conn.cursor()
    hace_7_dias = datetime.now() - timedelta(days=7)

    cur.execute("""
        SELECT l.id, l.nombre, l.doctor_id, l.fecha_actualizacion
        FROM leads l
        WHERE l.medical_status = 'Treatment Proposal Sent'
          AND l.doctor_id IS NOT NULL
          AND l.fecha_actualizacion <= %s
          AND l.sales_status NOT IN ('Lost', 'Won')
    """, (hace_7_dias,))
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, doctor_id, fecha_act = l
        dias = (datetime.now() - fecha_act).days if fecha_act else 0

        if not notificacion_existe(conn, lead_id, NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA, doctor_id):
            nid = crear_notificacion(
                conn, lead_id, NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA,
                "📋 Propuesta de tratamiento sin respuesta",
                f"📋 {nombre} tiene propuesta de tratamiento enviada desde hace {dias} días sin respuesta. Haz seguimiento.",
                doctor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [DOCTOR] Treatment Proposal sin respuesta: {creadas} notificaciones")
    return creadas


def detectar_citas_vencidas_doctor(conn):
    """
    Detecta citas vencidas para doctores desde DOS fuentes:
    
    1. agenda_doctor: citas formales con fecha_inicio <= NOW()
    2. leads.treatment_date: citas agendadas por asesor sin registro en agenda
    
    Solo notifica si el lead está en Pending Evaluation.
    """
    creadas = 0
    doctores_notificados = set()

    # ═══════════════════════════════════════════════════
    # FUENTE 1: Citas en agenda_doctor
    # ═══════════════════════════════════════════════════
    cur = conn.cursor()
    cur.execute("""
        SELECT ad.lead_id, ad.doctor_id as cita_doctor_id, 
               ad.fecha_inicio, l.nombre, l.doctor_id as lead_doctor_id
        FROM agenda_doctor ad
        JOIN leads l ON ad.lead_id = l.id
        WHERE ad.fecha_inicio <= NOW()
          AND l.medical_status = 'Pending Evaluation'
          AND l.sales_status IN ('Scheduled Appointment', 'Appointment Scheduled', 'Rescheduled Appointment')
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    citas_agenda = cur.fetchall()
    cur.close()

    for c in citas_agenda:
        lead_id, cita_doctor_id, fecha, nombre, lead_doctor_id = c
        fstr = fecha.strftime("%d/%m/%Y %H:%M") if fecha else ""
        
        doctor_id = lead_doctor_id or cita_doctor_id
        if not doctor_id:
            continue
            
        key = (lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id)
        if key in doctores_notificados:
            continue
        doctores_notificados.add(key)

        if not notificacion_existe(conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id):
            mensaje = (
                f"{nombre} tuvo cita el {fstr} y sigue en 'Pending Evaluation'. "
                f"Actualiza el estado médico."
            )
            nid = crear_notificacion(
                conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR,
                "⚠️ Cita vencida sin gestionar",
                mensaje, doctor_id, nombre
            )
            if nid:
                creadas += 1

    # ═══════════════════════════════════════════════════
    # FUENTE 2: Citas desde leads.treatment_date
    # (agendadas por asesor sin registro en agenda_doctor)
    # ═══════════════════════════════════════════════════
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.doctor_id, l.treatment_date
        FROM leads l
        WHERE l.treatment_date IS NOT NULL
          AND l.treatment_date <= NOW()
          AND l.medical_status = 'Pending Evaluation'
          AND l.doctor_id IS NOT NULL
          AND l.sales_status IN ('Scheduled Appointment', 'Appointment Scheduled', 'Rescheduled Appointment')
          AND l.sales_status NOT IN ('Lost', 'Won')
          AND NOT EXISTS (
              SELECT 1 FROM agenda_doctor ad 
              WHERE ad.lead_id = l.id AND ad.fecha_inicio = l.treatment_date
          )
    """)
    citas_leads = cur.fetchall()
    cur.close()

    for c in citas_leads:
        lead_id, nombre, doctor_id, treatment_date = c
        fstr = treatment_date.strftime("%d/%m/%Y %H:%M") if treatment_date else ""
        
        if not doctor_id:
            continue
            
        key = (lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id)
        if key in doctores_notificados:
            continue
        doctores_notificados.add(key)

        if not notificacion_existe(conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id):
            mensaje = (
                f"{nombre} tenía cita agendada para el {fstr} y sigue en 'Pending Evaluation'. "
                f"Actualiza el estado médico del paciente."
            )
            nid = crear_notificacion(
                conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR,
                "⚠️ Cita vencida sin gestionar",
                mensaje, doctor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [DOCTOR] Citas vencidas: {creadas} notificaciones (agenda + leads)")
    return creadas

# ══════════════════════════════════════════════════════════════
#  DETECCIÓN PARA ASESORES
# ══════════════════════════════════════════════════════════════

def detectar_citas_no_show(conn):
    """
    Detecta leads con appointment_status 'No Show'.
    Notifica al asesor asignado.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id, l.doctor_id
        FROM leads l
        WHERE l.appointment_status = 'No Show'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id, doctor_id = l

        if not notificacion_existe(conn, lead_id, NOTIF_CITA_NO_SHOW, asesor_id):
            doctor_info = f" con el doctor asignado" if doctor_id else ""
            nid = crear_notificacion(
                conn, lead_id, NOTIF_CITA_NO_SHOW,
                "😶 Paciente No Show - Requiere seguimiento",
                f"😶 {nombre} NO se presentó a su cita{doctor_info}. Contacta al paciente para reprogramar.",
                asesor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [ASESOR] Citas No Show: {creadas} notificaciones")
    return creadas


def detectar_citas_canceladas(conn):
    """
    Detecta leads con appointment_status 'Canceled'.
    Notifica al asesor asignado.
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

        if not notificacion_existe(conn, lead_id, NOTIF_CITA_CANCELADA, asesor_id):
            nid = crear_notificacion(
                conn, lead_id, NOTIF_CITA_CANCELADA,
                "❌ Cita cancelada - Requiere acción",
                f"❌ La cita de {nombre} fue cancelada. Contacta al paciente para reagendar o actualizar el estado.",
                asesor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [ASESOR] Citas Canceladas: {creadas} notificaciones")
    return creadas


def detectar_treatment_confirmed_pendientes(conn):
    """
    Detecta leads en 'Treatment Confirmed' que necesitan que el asesor
    agende el inicio del tratamiento.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id, l.doctor_id
        FROM leads l
        WHERE l.sales_status = 'Treatment Confirmed'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id, doctor_id = l

        if not notificacion_existe(conn, lead_id, NOTIF_TREATMENT_CONFIRMED_PENDIENTE, asesor_id):
            nid = crear_notificacion(
                conn, lead_id, NOTIF_TREATMENT_CONFIRMED_PENDIENTE,
                "✅ Tratamiento confirmado - Agendar inicio",
                f"✅ {nombre} tiene el tratamiento confirmado. Contacta al paciente para agendar la fecha de inicio del tratamiento.",
                asesor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [ASESOR] Treatment Confirmed pendientes: {creadas} notificaciones")
    return creadas


def detectar_callbacks_pendientes(conn):
    """
    Detecta booked_calls con fecha_llamada <= NOW() y estado = 'Pendiente'.
    Notifica al asesor asignado a la llamada.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT bc.id, bc.lead_id, bc.asesor_id, bc.fecha_llamada, l.nombre
        FROM booked_calls bc
        JOIN leads l ON bc.lead_id = l.id
        WHERE bc.estado = 'Pendiente' 
          AND bc.fecha_llamada <= NOW()
          AND bc.asesor_id IS NOT NULL
    """)
    calls = cur.fetchall()
    cur.close()

    creadas = 0
    for c in calls:
        _, lead_id, asesor_id, fecha, nombre = c
        hora = fecha.strftime("%H:%M") if fecha else ""

        if not notificacion_existe(conn, lead_id, NOTIF_CALLBACK_PENDIENTE, asesor_id):
            nid = crear_notificacion(
                conn, lead_id, NOTIF_CALLBACK_PENDIENTE,
                "📞 Callback pendiente - ¡Es hora de llamar!",
                f"📞 Tienes un callback programado para {nombre} a las {hora}. Realiza la llamada ahora.",
                asesor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [ASESOR] Callbacks pendientes: {creadas} notificaciones")
    return creadas


def detectar_leads_devueltos_asesor(conn):
    """
    Detecta leads cuyo medical_status fue cambiado a 'Candidate Rejected'
    y notifica al asesor asignado.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id, l.doctor_id
        FROM leads l
        WHERE l.medical_status = 'Candidate Rejected'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id, doctor_id = l

        if not notificacion_existe(conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR, asesor_id):
            if doctor_id and doctor_id != asesor_id:
                mensaje = f"{nombre} fue rechazado como candidato por el doctor asignado. Contacta al paciente para seguimiento."
            else:
                mensaje = f"{nombre} fue rechazado como candidato. Contacta al paciente para seguimiento."

            nid = crear_notificacion(
                conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR,
                "🔄 Lead devuelto por el doctor",
                mensaje,
                asesor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [ASESOR] Leads devueltos: {creadas} notificaciones")
    return creadas


def detectar_tratamientos_cancelados(conn):
    """
    Detecta leads cuyo appointment_status cambió a 'Canceled'.
    SOLO NOTIFICA AL ASESOR.
    El doctor ya recibe 'cita_vencida_doctor' si la cita sigue pendiente.
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

        # Solo notificar al asesor
        if not notificacion_existe(conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO, asesor_id):
            nid = crear_notificacion(
                conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO,
                "❌ Tratamiento cancelado - Requiere seguimiento",
                f"La cita de {nombre} fue cancelada. Como asesor, revisa el caso y contacta al paciente.",
                asesor_id, nombre
            )
            if nid:
                creadas += 1

    if creadas > 0:
        print(f"   📋 [ASESOR] Tratamientos cancelados: {creadas} notificaciones")
    return creadas


# ══════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL DE DETECCIÓN
# ══════════════════════════════════════════════════════════════

def detectar_y_crear_notificaciones(conn):
    """
    Ejecuta primero la limpieza automática y luego todas las detecciones masivas.
    Retorna el total de notificaciones creadas.
    """
    print("🔍 [NOTIFICACIONES] Iniciando ciclo de detección y limpieza...")

    # 1. LIMPIAR notificaciones que ya no aplican
    limpiadas = limpiar_notificaciones_huerfanas(conn)

    # 2. DETECTAR nuevas notificaciones
    # Para Doctores
    t1 = detectar_pending_evaluation_vencidas(conn)
    t2 = detectar_treatment_proposal_sin_respuesta(conn)
    t3 = detectar_citas_vencidas_doctor(conn)

    # Para Asesores
    t4 = detectar_citas_no_show(conn)
    t5 = detectar_citas_canceladas(conn)
    t6 = detectar_treatment_confirmed_pendientes(conn)
    t7 = detectar_callbacks_pendientes(conn)
    t8 = detectar_leads_devueltos_asesor(conn)
    t9 = detectar_tratamientos_cancelados(conn)

    total_creadas = t1 + t2 + t3 + t4 + t5 + t6 + t7 + t8 + t9

    if total_creadas > 0:
        print(f"✅ [NOTIFICACIONES] Creadas: {total_creadas} nuevas")
        print(f"   Doctores: Pending Eval={t1}, Proposal sin resp={t2}, Citas venc={t3}")
        print(f"   Asesores: No Show={t4}, Cancel={t5}, Treat Conf={t6}, Callbacks={t7}, Devueltos={t8}, Trat Cancel={t9}")
    else:
        print("ℹ️ [NOTIFICACIONES] No se encontraron nuevas notificaciones para crear")

    return total_creadas


# ══════════════════════════════════════════════════════════════
#  DIAGNÓSTICO
# ══════════════════════════════════════════════════════════════

def diagnosticar_asignaciones(conn):
    """Función de diagnóstico de notificaciones."""
    print("\n📊 DIAGNÓSTICO DE NOTIFICACIONES")
    print("=" * 60)

    cur = conn.cursor()

    cur.execute("""
        SELECT tipo, COUNT(*) as total, 
               COUNT(DISTINCT usuario_id) as usuarios_unicos
        FROM notificaciones
        WHERE estado = 'pendiente'
        GROUP BY tipo
        ORDER BY total DESC
    """)
    resumen = cur.fetchall()

    print(f"\n📈 RESUMEN DE NOTIFICACIONES PENDIENTES:")
    for r in resumen:
        print(f"  - {r[0]}: {r[1]} notificaciones, {r[2]} usuarios únicos")

    cur.close()
    return {
        "resumen": [{"tipo": r[0], "total": r[1], "usuarios": r[2]} for r in resumen]
    }