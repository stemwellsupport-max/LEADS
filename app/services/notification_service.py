# app/services/notification_service.py
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from typing import List, Dict, Optional

NOTIF_PENDING_EVALUATION_VENCIDA = "pending_evaluation_vencida"
NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA = "treatment_proposal_sin_respuesta"
NOTIF_CITA_VENCIDA_DOCTOR = "cita_vencida_doctor"
NOTIF_CITA_NO_SHOW = "cita_no_show"
NOTIF_CITA_CANCELADA = "cita_cancelada"
NOTIF_TREATMENT_CONFIRMED_PENDIENTE = "treatment_confirmed_pendiente"
NOTIF_CALLBACK_PENDIENTE = "callback_pendiente"
NOTIF_LLAMADA_PENDIENTE = "llamada_pendiente"
NOTIF_LEAD_DEVUELTO_ASESOR = "lead_devuelto_asesor"
NOTIF_TRATAMIENTO_CANCELADO = "tratamiento_cancelado"

def crear_notificacion(conn, lead_id, tipo, asunto, mensaje, usuario_id, lead_name=None):
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO notificaciones (lead_id, tipo, asunto, mensaje, fecha_envio, estado, usuario_id, lead_name)
            VALUES (%s, %s, %s, %s, NOW(), 'pendiente', %s, %s) RETURNING id
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
    """Elimina una notificación de la tabla."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notificaciones WHERE id=%s AND usuario_id=%s",
        (notificacion_id, usuario_id)
    )
    ok = cur.rowcount > 0
    conn.commit()
    cur.close()
    return ok


def resolver_todas(conn, usuario_id):
    """Elimina todas las notificaciones pendientes de un usuario."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notificaciones WHERE usuario_id=%s AND estado='pendiente'",
        (usuario_id,)
    )
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def resolver_notificaciones_lead(conn, lead_id):
    """Elimina todas las notificaciones de un lead."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notificaciones WHERE lead_id=%s AND estado='pendiente'",
        (lead_id,)
    )
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def resolver_notificaciones_por_tipo(conn, lead_id, tipos):
    """Elimina notificaciones pendientes de un lead por tipos específicos."""
    if not tipos:
        return 0
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM notificaciones WHERE lead_id=%s AND estado='pendiente' AND tipo = ANY(%s)",
        (lead_id, tipos)
    )
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count

def eliminar_notificaciones_lead(conn, lead_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM notificaciones WHERE lead_id=%s", (lead_id,))
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count

def listar_notificaciones(conn, usuario_id, solo_pendientes=True):
    cur = conn.cursor()
    q = "SELECT n.id, n.lead_id, n.tipo, n.asunto, n.mensaje, n.fecha_envio, n.estado, n.usuario_id, n.lead_name FROM notificaciones n WHERE n.usuario_id=%s"
    if solo_pendientes: q += " AND n.estado='pendiente'"
    q += " ORDER BY n.fecha_envio DESC LIMIT 200"
    cur.execute(q, (usuario_id,))
    rows = cur.fetchall()
    cols = ["id","lead_id","tipo","asunto","mensaje","fecha_envio","estado","usuario_id","lead_name"]
    resultado = []
    for row in rows:
        d = {}
        for i, col in enumerate(cols):
            val = row[i]
            if isinstance(val, datetime): val = val.isoformat()
            d[col] = val
        resultado.append(d)
    cur.close()
    return resultado

def contar_pendientes(conn, usuario_id):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notificaciones WHERE usuario_id=%s AND estado='pendiente'", (usuario_id,))
    c = cur.fetchone()[0]
    cur.close()
    return c

def notificacion_existe(conn, lead_id, tipo, usuario_id):
    cur = conn.cursor()
    cur.execute("SELECT id FROM notificaciones WHERE lead_id=%s AND tipo=%s AND usuario_id=%s AND estado='pendiente' LIMIT 1", (lead_id, tipo, usuario_id))
    ex = cur.fetchone() is not None
    cur.close()
    return ex

def limpiar_notificaciones_por_estado(conn, lead_id):
    cur = conn.cursor()
    total = 0
    cur.execute("SELECT sales_status, appointment_status, medical_status, cita_confirmada, treatment_confirmed FROM leads WHERE id=%s", (lead_id,))
    lead = cur.fetchone()
    if not lead: cur.close(); return 0
    sales_status = lead[0] or ""
    appointment_status = lead[1] or ""
    medical_status = lead[2] or ""
    cita_confirmada = lead[3] or False
    treatment_confirmed = lead[4] or False
    tipos_a_limpiar = []
    if medical_status and medical_status != "Pending Evaluation":
        tipos_a_limpiar.extend([NOTIF_PENDING_EVALUATION_VENCIDA, NOTIF_CITA_VENCIDA_DOCTOR])
    if medical_status and medical_status != "Treatment Proposal Sent":
        tipos_a_limpiar.append(NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA)
    if medical_status and medical_status != "Candidate Rejected":
        tipos_a_limpiar.append(NOTIF_LEAD_DEVUELTO_ASESOR)
    if appointment_status and appointment_status != "No Show":
        tipos_a_limpiar.append(NOTIF_CITA_NO_SHOW)
    if appointment_status and appointment_status != "Canceled":
        tipos_a_limpiar.extend([NOTIF_CITA_CANCELADA, NOTIF_TRATAMIENTO_CANCELADO])
    
    # REGLA ADICIONAL: Si el asesor ya movió el lead a otro estado 
    # (No Answer, Callback, etc.) → limpiar notificaciones de No Show/Cancel
    if sales_status in ("No Answer", "Callback", "First Contact", "New Lead", "Scheduled Appointment"):
        tipos_a_limpiar.extend([
            NOTIF_CITA_NO_SHOW, 
            NOTIF_CITA_CANCELADA, 
            NOTIF_TRATAMIENTO_CANCELADO, 
            NOTIF_LEAD_DEVUELTO_ASESOR
        ])
    if sales_status and "Scheduled" not in sales_status:
        tipos_a_limpiar.append(NOTIF_CITA_VENCIDA_DOCTOR)
    if sales_status and sales_status != "Treatment Confirmed":
        tipos_a_limpiar.append(NOTIF_TREATMENT_CONFIRMED_PENDIENTE)
    if cita_confirmada:
        tipos_a_limpiar.extend([NOTIF_CITA_VENCIDA_DOCTOR, NOTIF_CITA_CANCELADA])
    if treatment_confirmed:
        tipos_a_limpiar.extend([NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA, NOTIF_TREATMENT_CONFIRMED_PENDIENTE])
    if sales_status in ("Treatment in Progress", "Won", "Lost"):
        cur.execute("UPDATE notificaciones SET estado='resuelta', resuelta_por=usuario_id, fecha_resolucion=NOW() WHERE lead_id=%s AND estado='pendiente'", (lead_id,))
        total = cur.rowcount
        conn.commit(); cur.close()
        if total > 0: print(f"🧹 Lead #{lead_id}: {total} notificaciones resueltas ({sales_status})")
        return total
    tipos_a_limpiar = list(set(tipos_a_limpiar))
    if tipos_a_limpiar:
        cur.execute("UPDATE notificaciones SET estado='resuelta', resuelta_por=usuario_id, fecha_resolucion=NOW() WHERE lead_id=%s AND estado='pendiente' AND tipo=ANY(%s)", (lead_id, tipos_a_limpiar))
        total = cur.rowcount
    conn.commit(); cur.close()
    if total > 0: print(f"🧹 Lead #{lead_id}: {total} notif resueltas (S={sales_status}, A={appointment_status}, M={medical_status})")
    return total

def limpiar_notificaciones_huerfanas(conn):
    total_resueltas = 0; cur = conn.cursor()
    updates = [
        ("pending_evaluation_vencida", "medical_status != 'Pending Evaluation'"),
        ("treatment_proposal_sin_respuesta", "medical_status != 'Treatment Proposal Sent'"),
        ("cita_vencida_doctor", "sales_status NOT IN ('Scheduled Appointment','Appointment Scheduled')"),
        ("cita_no_show", "appointment_status != 'No Show'"),
        ("cita_cancelada", "appointment_status != 'Canceled'"),
        ("treatment_confirmed_pendiente", "sales_status != 'Treatment Confirmed'"),
        ("tratamiento_cancelado", "appointment_status != 'Canceled'"),
        ("lead_devuelto_asesor", "medical_status != 'Candidate Rejected'"),
    ]
    for tipo, cond in updates:
        cur.execute(f"UPDATE notificaciones n SET estado='resuelta', resuelta_por=n.usuario_id, fecha_resolucion=NOW() FROM leads l WHERE n.lead_id=l.id AND n.tipo='{tipo}' AND n.estado='pendiente' AND l.{cond}")
        total_resueltas += cur.rowcount
    cur.execute("DELETE FROM notificaciones a USING notificaciones b WHERE a.lead_id=b.lead_id AND a.tipo=b.tipo AND a.usuario_id=b.usuario_id AND a.estado='pendiente' AND b.estado='pendiente' AND a.fecha_envio < b.fecha_envio")
    duplicados = cur.rowcount
    cur.execute("DELETE FROM notificaciones n WHERE NOT EXISTS (SELECT 1 FROM leads l WHERE l.id=n.lead_id)")
    huerfanos = cur.rowcount
    conn.commit(); cur.close()
    total = total_resueltas + duplicados + huerfanos
    if total > 0: print(f"🧹 Auto-limpieza: {total_resueltas} resueltas, {duplicados} duplicados, {huerfanos} huérfanos")
    return total

def detectar_pending_evaluation_vencidas(conn):
    cur = conn.cursor()
    cur.execute("SELECT l.id,l.nombre,l.doctor_id,l.treatment_date FROM leads l WHERE l.medical_status='Pending Evaluation' AND l.doctor_id IS NOT NULL AND l.treatment_date IS NOT NULL AND l.treatment_date<=NOW() AND l.sales_status NOT IN ('Lost','Won')")
    leads = cur.fetchall(); cur.close()
    creadas = 0
    for l in leads:
        lid,nombre,did,td = l
        fs = td.strftime("%d/%m/%Y %H:%M") if td else ""
        if not notificacion_existe(conn,lid,NOTIF_PENDING_EVALUATION_VENCIDA,did):
            if crear_notificacion(conn,lid,NOTIF_PENDING_EVALUATION_VENCIDA,"🩺 Consulta pendiente",f"⚠️ {nombre} tuvo consulta el {fs} y sigue en Pending Evaluation.",did,nombre): creadas+=1
    if creadas>0: print(f"   📋 [DOCTOR] Pending Evaluation: {creadas}")
    return creadas

def detectar_treatment_proposal_sin_respuesta(conn):
    cur = conn.cursor()
    h7 = datetime.now()-timedelta(days=7)
    cur.execute("SELECT l.id,l.nombre,l.doctor_id,l.fecha_actualizacion FROM leads l WHERE l.medical_status='Treatment Proposal Sent' AND l.doctor_id IS NOT NULL AND l.fecha_actualizacion<=%s AND l.sales_status NOT IN ('Lost','Won')",(h7,))
    leads = cur.fetchall(); cur.close()
    creadas = 0
    for l in leads:
        lid,nombre,did,fa = l
        dias = (datetime.now()-fa).days if fa else 0
        if not notificacion_existe(conn,lid,NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA,did):
            if crear_notificacion(conn,lid,NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA,"📋 Propuesta sin respuesta",f"📋 {nombre} tiene propuesta enviada hace {dias} días sin respuesta.",did,nombre): creadas+=1
    if creadas>0: print(f"   📋 [DOCTOR] Proposal sin resp: {creadas}")
    return creadas

def detectar_citas_vencidas_doctor(conn):
    """
    Detecta leads con citas vencidas que siguen en Pending Evaluation.
    SOLO crea una notificación si NO existe ya una pendiente del mismo tipo.
    Usa DISTINCT ON para evitar duplicados del mismo lead.
    """
    creadas = 0
    cur = conn.cursor()
    
    # Buscar citas vencidas en agenda_doctor - solo la más reciente por lead
    cur.execute("""
        SELECT DISTINCT ON (ad.lead_id) 
            ad.lead_id, ad.doctor_id, ad.fecha_inicio, l.nombre
        FROM agenda_doctor ad 
        JOIN leads l ON ad.lead_id = l.id 
        WHERE ad.fecha_inicio <= NOW() 
          AND l.medical_status = 'Pending Evaluation' 
          AND l.sales_status IN ('Scheduled Appointment', 'Rescheduled Appointment') 
          AND l.sales_status NOT IN ('Lost', 'Won')
        ORDER BY ad.lead_id, ad.fecha_inicio DESC
    """)
    
    for row in cur.fetchall():
        lid, did, fecha, nombre = row
        
        if not did:
            continue
        
        # Solo crear si NO existe ya una pendiente
        if not notificacion_existe(conn, lid, NOTIF_CITA_VENCIDA_DOCTOR, did):
            nid = crear_notificacion(
                conn, lid, NOTIF_CITA_VENCIDA_DOCTOR,
                "⚠️ Cita vencida sin gestionar",
                f"⚠️ {nombre} tuvo cita el {fecha.strftime('%d/%m/%Y %H:%M')} y sigue en Pending Evaluation.",
                did, nombre
            )
            if nid:
                creadas += 1
    
    # También buscar en leads sin agenda_doctor
    cur.execute("""
        SELECT l.id, l.nombre, l.doctor_id, l.treatment_date 
        FROM leads l 
        WHERE l.treatment_date IS NOT NULL 
          AND l.treatment_date <= NOW() 
          AND l.medical_status = 'Pending Evaluation' 
          AND l.doctor_id IS NOT NULL 
          AND l.sales_status IN ('Scheduled Appointment', 'Rescheduled Appointment') 
          AND l.sales_status NOT IN ('Lost', 'Won')
          AND NOT EXISTS (
              SELECT 1 FROM agenda_doctor ad WHERE ad.lead_id = l.id
          )
    """)
    
    for row in cur.fetchall():
        lid, nombre, did, td = row
        
        if not did:
            continue
        
        if not notificacion_existe(conn, lid, NOTIF_CITA_VENCIDA_DOCTOR, did):
            nid = crear_notificacion(
                conn, lid, NOTIF_CITA_VENCIDA_DOCTOR,
                "⚠️ Cita vencida sin gestionar",
                f"⚠️ {nombre} tenía cita el {td.strftime('%d/%m/%Y %H:%M')} y sigue en Pending Evaluation.",
                did, nombre
            )
            if nid:
                creadas += 1
    
    cur.close()
    
    if creadas > 0:
        print(f"   📋 [DOCTOR] Citas vencidas: {creadas} nuevas")
    return creadas

def detectar_citas_no_show(conn):
    """
    Detecta leads con appointment_status 'No Show'.
    SOLO notifica si el sales_status es 'Cancelled Appointment'.
    Si el asesor ya movió el lead a No Answer/Callback, NO notificar.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id, l.doctor_id
        FROM leads l
        WHERE l.appointment_status = 'No Show'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status = 'Cancelled Appointment'  -- ← SOLO si sigue en Cancelled
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
    cur=conn.cursor()
    cur.execute("SELECT l.id,l.nombre,l.asesor_id FROM leads l WHERE l.appointment_status='Canceled' AND l.asesor_id IS NOT NULL AND l.sales_status NOT IN ('Lost','Won')")
    leads=cur.fetchall(); cur.close()
    creadas=0
    for l in leads:
        lid,nombre,aid=l
        if not notificacion_existe(conn,lid,NOTIF_CITA_CANCELADA,aid):
            if crear_notificacion(conn,lid,NOTIF_CITA_CANCELADA,"❌ Cita cancelada",f"❌ La cita de {nombre} fue cancelada. Contacta al paciente.",aid,nombre): creadas+=1
    if creadas>0: print(f"   📋 [ASESOR] Canceladas: {creadas}")
    return creadas

def detectar_treatment_confirmed_pendientes(conn):
    cur=conn.cursor()
    cur.execute("SELECT l.id,l.nombre,l.asesor_id FROM leads l WHERE l.sales_status='Treatment Confirmed' AND l.asesor_id IS NOT NULL AND l.sales_status NOT IN ('Lost','Won')")
    leads=cur.fetchall(); cur.close()
    creadas=0
    for l in leads:
        lid,nombre,aid=l
        if not notificacion_existe(conn,lid,NOTIF_TREATMENT_CONFIRMED_PENDIENTE,aid):
            if crear_notificacion(conn,lid,NOTIF_TREATMENT_CONFIRMED_PENDIENTE,"✅ Tratamiento confirmado",f"✅ {nombre} tiene tratamiento confirmado. Agenda inicio.",aid,nombre): creadas+=1
    if creadas>0: print(f"   📋 [ASESOR] Treat Conf: {creadas}")
    return creadas

def detectar_callbacks_pendientes(conn):
    cur=conn.cursor()
    cur.execute("SELECT bc.lead_id,bc.asesor_id,bc.fecha_llamada,l.nombre FROM booked_calls bc JOIN leads l ON bc.lead_id=l.id WHERE bc.estado='Pendiente' AND bc.fecha_llamada<=NOW() AND bc.asesor_id IS NOT NULL")
    calls=cur.fetchall(); cur.close()
    creadas=0
    for c in calls:
        lid,aid,f,nombre=c
        if not notificacion_existe(conn,lid,NOTIF_CALLBACK_PENDIENTE,aid):
            if crear_notificacion(conn,lid,NOTIF_CALLBACK_PENDIENTE,"📞 Callback pendiente",f"📞 Callback para {nombre} a las {f.strftime('%H:%M')}.",aid,nombre): creadas+=1
    if creadas>0: print(f"   📋 [ASESOR] Callbacks: {creadas}")
    return creadas

def detectar_leads_devueltos_asesor(conn):
    cur=conn.cursor()
    cur.execute("SELECT l.id,l.nombre,l.asesor_id,l.doctor_id FROM leads l WHERE l.medical_status='Candidate Rejected' AND l.asesor_id IS NOT NULL AND l.sales_status NOT IN ('Lost','Won')")
    leads=cur.fetchall(); cur.close()
    creadas=0
    for l in leads:
        lid,nombre,aid,did=l
        if not notificacion_existe(conn,lid,NOTIF_LEAD_DEVUELTO_ASESOR,aid):
            msg = f"{nombre} fue rechazado como candidato por el doctor. Contacta al paciente." if did and did!=aid else f"{nombre} fue rechazado como candidato."
            if crear_notificacion(conn,lid,NOTIF_LEAD_DEVUELTO_ASESOR,"🔄 Lead devuelto",msg,aid,nombre): creadas+=1
    if creadas>0: print(f"   📋 [ASESOR] Devueltos: {creadas}")
    return creadas

def detectar_tratamientos_cancelados(conn):
    cur=conn.cursor()
    cur.execute("SELECT l.id,l.nombre,l.asesor_id FROM leads l WHERE l.appointment_status='Canceled' AND l.asesor_id IS NOT NULL AND l.sales_status NOT IN ('Lost','Won')")
    leads=cur.fetchall(); cur.close()
    creadas=0
    for l in leads:
        lid,nombre,aid=l
        if not notificacion_existe(conn,lid,NOTIF_TRATAMIENTO_CANCELADO,aid):
            if crear_notificacion(conn,lid,NOTIF_TRATAMIENTO_CANCELADO,"❌ Tratamiento cancelado",f"La cita de {nombre} fue cancelada. Revisa el caso.",aid,nombre): creadas+=1
    if creadas>0: print(f"   📋 [ASESOR] Trat Cancel: {creadas}")
    return creadas

def detectar_y_crear_notificaciones(conn):
    print("🔍 [NOTIFICACIONES] Iniciando ciclo...")
    limpiadas = limpiar_notificaciones_huerfanas(conn)
    t1=detectar_pending_evaluation_vencidas(conn)
    t2=detectar_treatment_proposal_sin_respuesta(conn)
    t3=detectar_citas_vencidas_doctor(conn)
    t4=detectar_citas_no_show(conn)
    t5=detectar_citas_canceladas(conn)
    t6=detectar_treatment_confirmed_pendientes(conn)
    t7=detectar_callbacks_pendientes(conn)
    t8=detectar_leads_devueltos_asesor(conn)
    t9=detectar_tratamientos_cancelados(conn)
    total=t1+t2+t3+t4+t5+t6+t7+t8+t9
    if total>0: print(f"✅ [NOTIFICACIONES] Creadas: {total}")
    else: print("ℹ️ [NOTIFICACIONES] Sin nuevas")
    return total

def diagnosticar_asignaciones(conn):
    cur=conn.cursor()
    cur.execute("SELECT tipo,COUNT(*),COUNT(DISTINCT usuario_id) FROM notificaciones WHERE estado='pendiente' GROUP BY tipo ORDER BY COUNT(*) DESC")
    resumen=cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM notificaciones WHERE estado='pendiente'")
    total=cur.fetchone()[0]
    cur.close()
    return {"resumen":[{"tipo":r[0],"total":r[1],"usuarios":r[2]} for r in resumen],"total_pendientes":total}