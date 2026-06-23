# app/services/lead_service.py
# -*- coding: utf-8 -*-
from datetime import datetime, date
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger("stemwell")

# ===========================================================
#  NOTIFICACIONES
# ===========================================================
from app.services.notification_service import (
    crear_notificacion,
    notificacion_existe,
    resolver_notificaciones_lead,
    limpiar_notificaciones_por_estado,
    NOTIF_LLAMADA_PENDIENTE,
    NOTIF_CITA_VENCIDA_DOCTOR,
    NOTIF_LEAD_DEVUELTO_ASESOR,
    NOTIF_TRATAMIENTO_CANCELADO,
    NOTIF_CITA_NO_SHOW,
    NOTIF_CITA_CANCELADA,
    NOTIF_PENDING_EVALUATION_VENCIDA,
    NOTIF_TREATMENT_PROPOSAL_SIN_RESPUESTA,
    NOTIF_TREATMENT_CONFIRMED_PENDIENTE,
)

def _notificar_lead_devuelto_asesor(conn, lead, motivo):
    """Notifica al asesor cuando el doctor devuelve un lead (canceló/no-show)"""
    asesor_id = lead.get("asesor_id")
    lead_id = lead.get("id")
    lead_name = lead.get("nombre") or "Paciente"
    
    if asesor_id:
        cur = conn.cursor()
        cur.execute("""
            UPDATE notificaciones 
            SET estado = 'resuelta', resuelta_por = usuario_id, fecha_resolucion = NOW()
            WHERE lead_id = %s AND estado = 'pendiente' 
              AND tipo IN ('lead_devuelto_asesor', 'cita_no_show', 'cita_cancelada', 
                          'tratamiento_cancelado', 'cita_vencida_doctor')
        """, (lead_id,))
        conn.commit()
        cur.close()
        
        if not notificacion_existe(conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR, asesor_id):
            crear_notificacion(
                conn,
                lead_id=lead_id,
                tipo=NOTIF_LEAD_DEVUELTO_ASESOR,
                asunto="🔄 Lead devuelto a tu bandeja",
                mensaje=f"{lead_name} fue devuelto por el doctor. Motivo: {motivo}. Debes reagendar o dar seguimiento.",
                usuario_id=asesor_id,
                lead_name=lead_name
            )


def _notificar_tratamiento_cancelado_asesor(conn, lead, motivo):
    """Notifica al asesor cuando se cancela un tratamiento o cita"""
    asesor_id = lead.get("asesor_id")
    lead_id = lead.get("id")
    lead_name = lead.get("nombre") or "Paciente"
    
    if asesor_id:
        cur = conn.cursor()
        cur.execute("""
            UPDATE notificaciones 
            SET estado = 'resuelta', resuelta_por = usuario_id, fecha_resolucion = NOW()
            WHERE lead_id = %s AND estado = 'pendiente' 
              AND tipo IN ('tratamiento_cancelado', 'cita_cancelada', 'lead_devuelto_asesor')
        """, (lead_id,))
        conn.commit()
        cur.close()
        
        if not notificacion_existe(conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO, asesor_id):
            crear_notificacion(
                conn,
                lead_id=lead_id,
                tipo=NOTIF_TRATAMIENTO_CANCELADO,
                asunto="❌ Cita/Tratamiento cancelado",
                mensaje=f"{lead_name}: {motivo}. Debes reagendar la cita o dar seguimiento al paciente.",
                usuario_id=asesor_id,
                lead_name=lead_name
            )

# ===========================================================
#  AUXILIARES AGENDA
# ===========================================================
def _parse_fecha(v):
    if not v:
        return None
    s = str(v).strip()
    
    if " " in s and len(s) >= 16:
        parts = s.split(" ")
        if len(parts) >= 2:
            hora = parts[1]
            if hora.count(":") == 1:
                s = s + ":00"
            elif hora.count(":") == 0:
                s = s + ":00:00"
        return s
    
    if "T" in s:
        s = s.replace("T", " ")
        if s.count(":") == 1:
            s = s + ":00"
        elif s.count(":") == 0:
            s = s + ":00:00"
        return s
    
    if len(s) == 10 and s.count("-") == 2:
        return s + " 00:00:00"
    
    return s

def _sync_agenda(conn, lead_id, treatment_date, doctor_id, estado='Scheduled'):
    if not treatment_date or not doctor_id:
        return
    fecha = _parse_fecha(treatment_date)
    cur = conn.cursor()
    cur.execute("SELECT id FROM agenda_doctor WHERE lead_id=%s", (lead_id,))
    if cur.fetchone():
        cur.execute("""UPDATE agenda_doctor
            SET doctor_id=%s, fecha_inicio=%s::timestamp, fecha_fin=%s::timestamp,
                estado=%s, fecha_actualizacion=CURRENT_TIMESTAMP
            WHERE lead_id=%s""", (doctor_id, fecha, fecha, estado, lead_id))
    else:
        cur.execute("""INSERT INTO agenda_doctor (lead_id,doctor_id,fecha_inicio,fecha_fin,estado,tipo)
            VALUES (%s,%s,%s::timestamp,%s::timestamp,%s,'Consulta')""",
            (lead_id, doctor_id, fecha, fecha, estado))
    conn.commit()
    cur.close()

def _delete_from_agenda(conn, lead_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM agenda_doctor WHERE lead_id=%s", (lead_id,))
    conn.commit()
    cur.close()

def _update_agenda_estado(conn, lead_id, estado):
    cur = conn.cursor()
    cur.execute("UPDATE agenda_doctor SET estado=%s, fecha_actualizacion=CURRENT_TIMESTAMP WHERE lead_id=%s",
                (estado, lead_id))
    conn.commit()
    cur.close()

def _update_agenda_fecha(conn, lead_id, treatment_date, estado='Rescheduled'):
    if not treatment_date:
        return
    fecha = _parse_fecha(treatment_date)
    cur = conn.cursor()
    cur.execute("""UPDATE agenda_doctor
        SET fecha_inicio=%s::timestamp, fecha_fin=%s::timestamp, estado=%s,
            fecha_actualizacion=CURRENT_TIMESTAMP
        WHERE lead_id=%s""", (fecha, fecha, estado, lead_id))
    conn.commit()
    cur.close()

# ===========================================================
#  FORMAT LEAD
# ===========================================================
def _dt(v):
    if not v:
        return None
    s = str(v).strip()
    if "T" in s:
        return s.split("T")[0]
    if " " in s:
        return s.split(" ")[0]
    if len(s) > 10:
        return s[:10]
    return s


def _dt_full(v):
    if not v:
        return None
    s = str(v).strip()
    if hasattr(v, 'isoformat'):
        return v.isoformat()
    if "T" in s:
        return s
    if " " in s:
        return s.replace(" ", "T")
    if len(s) == 10 and s.count("-") == 2:
        return s
    return s


def format_lead(l):
    return {
        "id": l["id"],
        "nombre": l["nombre"],
        "telefono": l["telefono"],
        "email": l["email"],
        "categoria": l.get("categoria") or "",
        "canal": l.get("canal") or "",
        "genero": l.get("genero") or "",
        "ciudad": l.get("pais") or "",
        "pais": l.get("pais") or "",
        "sales_status": l.get("sales_status"),
        "appointment_status": l.get("appointment_status"),
        "medical_status": l.get("medical_status"),
        "asesor_id": l.get("asesor_id"),
        "asesor_nombre": l.get("asesor_nombre"),
        "doctor_id": l.get("doctor_id"),
        "doctor_nombre": l.get("doctor_nombre"),
        "notas": l.get("notas") or "",
        "comentarios": l.get("comentarios") or "",
        "rejection_reason": l.get("rejection_reason"),
        "quit_reason": l.get("quit_reason"),
        "medilink_numero": l.get("medilink_numero"),
        "cita_confirmada": l.get("cita_confirmada", False),
        "treatment_confirmed": l.get("treatment_confirmed", False),
        "treatment_date": _dt_full(l.get("treatment_date")),
        "treatment_start_date": _dt_full(l.get("treatment_start_date")),
        "treatment_end_date": _dt_full(l.get("treatment_end_date")),
        "next_treatment_date": _dt_full(l.get("next_treatment_date")),
        "treatment_completed": l.get("treatment_completed", False),
        "fecha_creacion": _dt(l.get("fecha_creacion")),
        "fecha_actualizacion": _dt(l.get("fecha_actualizacion")),
        "admission_date": _dt(l.get("admission_date") or l.get("fecha_creacion")),
        "last_contact_date": _dt(l.get("last_contact_date") or l.get("fecha_actualizacion")),
        "pipeline": l.get("pipeline") or "",
        "favorito": l.get("favorito", False),
        "consulta_agendada": l.get("consulta_agendada", False),
        "primera_agenda_date": _dt(l.get("primera_agenda_date")),
        "primer_contacto": l.get("primer_contacto", False),
        "cita_asistida": l.get("cita_asistida", False),
        "evaluacion_realizada": l.get("evaluacion_realizada", False),
        "propuesta_enviada": l.get("propuesta_enviada", False),
        "propuesta_aceptada": l.get("propuesta_aceptada", False),
        "tratamiento_iniciado": l.get("tratamiento_iniciado", False),
        "tratamiento_completado": l.get("tratamiento_completado", False),
        "fecha_primer_contacto": _dt(l.get("fecha_primer_contacto")),
        "fecha_cita_asistida": _dt(l.get("fecha_cita_asistida")),
        "fecha_evaluacion": _dt(l.get("fecha_evaluacion")),
        "fecha_propuesta_enviada": _dt(l.get("fecha_propuesta_enviada")),
        "fecha_propuesta_aceptada": _dt(l.get("fecha_propuesta_aceptada")),
        "fecha_tratamiento_inicio": _dt(l.get("fecha_tratamiento_inicio")),
        "fecha_won": _dt(l.get("fecha_won")),
    }

# ===========================================================
#  GET LEADS
# ===========================================================
def get_leads_for_user(conn, usuario_id: int, estado: str = None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rol FROM usuarios WHERE id=%s", (usuario_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        raise ValueError("Usuario no encontrado")
    rol = user["rol"]

    base = """SELECT l.*, d.nombre AS doctor_nombre, a.nombre AS asesor_nombre
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id=d.id
        LEFT JOIN usuarios a ON l.asesor_id=a.id"""

    if rol == "asesor":
        where = "WHERE l.asesor_id=%s AND l.sales_status != 'Lost'"
        params = [usuario_id]
        if estado:
            where += " AND l.sales_status=%s"
            params.append(estado)
    elif rol == "doctor":
        where = """WHERE l.doctor_id=%s AND l.medical_status IS NOT NULL
            AND l.medical_status NOT IN ('Treatment Completed','Candidate Rejected')
            AND l.sales_status != 'Lost'"""
        params = [usuario_id]
        if estado:
            where = "WHERE l.doctor_id=%s AND l.medical_status=%s AND l.sales_status != 'Lost'"
            params = [usuario_id, estado]
    else:
        where = "WHERE 1=1"
        params = []
        if estado:
            where += " AND (l.sales_status=%s OR l.medical_status=%s)"
            params = [estado, estado]

    cur.execute(base + " " + where + " ORDER BY l.fecha_actualizacion DESC", params)
    leads = cur.fetchall()
    cur.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

# ===========================================================
#  CREATE LEAD
# ===========================================================
def create_lead(conn, data):
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if data.email:
        cur.execute("SELECT id,nombre FROM leads WHERE email=%s AND email<>''", (data.email,))
        dup = cur.fetchone()
        if dup:
            cur.close()
            raise ValueError(f"Ya existe un lead con ese email: {dup['nombre']}")
    if data.telefono:
        cur.execute("SELECT id,nombre FROM leads WHERE telefono=%s AND telefono<>''", (data.telefono,))
        dup = cur.fetchone()
        if dup:
            cur.close()
            raise ValueError(f"Ya existe un lead con ese teléfono: {dup['nombre']}")

    cur2 = conn.cursor()
    asesor_id = data.asesor_id
    if not asesor_id:
        cur2.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
        row = cur2.fetchone()
        if row: asesor_id = row[0]

    cur2.execute(
        "INSERT INTO leads (nombre,telefono,email,categoria,canal,genero,ciudad,pais,notas,"
        "sales_status,asesor_id,doctor_id,creado_por,pipeline,last_contact_date,admission_date,favorito) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE,CURRENT_DATE,%s) RETURNING id",
        (data.nombre, data.telefono, data.email, data.categoria, data.canal,
        data.genero, data.ciudad, data.pais, data.notas,
        data.sales_status_inicial or "New Lead",
        asesor_id, data.doctor_id, data.creado_por, data.pipeline, data.favorito)
    )
    lead_id = cur2.fetchone()[0]
    conn.commit()
    cur.close()
    cur2.close()
    return lead_id

# ===========================================================
#  TRANSFERIR LEAD
# ===========================================================
def transferir_lead(conn, lead_id: int, nuevo_asesor_id: int, usuario_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id,nombre,asesor_id FROM leads WHERE id=%s", (lead_id,))
    lead = cur.fetchone()
    if not lead:
        cur.close()
        raise ValueError("Lead no encontrado")

    cur.execute("SELECT id,nombre FROM usuarios WHERE id=%s AND rol='asesor' AND activo=true", (nuevo_asesor_id,))
    nuevo_asesor = cur.fetchone()
    if not nuevo_asesor:
        cur.close()
        raise ValueError("Asesor destino no válido")

    cur.execute("SELECT nombre FROM usuarios WHERE id=%s", (lead["asesor_id"],))
    row = cur.fetchone()
    asesor_anterior_nombre = row["nombre"] if row else "Desconocido"

    cur.execute("UPDATE leads SET asesor_id=%s, fecha_actualizacion=CURRENT_TIMESTAMP WHERE id=%s",
                (nuevo_asesor_id, lead_id))
    cur.execute(
        "INSERT INTO historial_estados (lead_id,estado_anterior,estado_nuevo,cambiado_por,comentario) "
        "VALUES (%s,%s,%s,%s,%s)",
        (lead_id, f"ASESOR:{asesor_anterior_nombre}", f"ASESOR:{nuevo_asesor['nombre']}",
         usuario_id, f"Lead transferido de {asesor_anterior_nombre} a {nuevo_asesor['nombre']}")
    )
    conn.commit()
    cur.close()
    return {"message": f"Lead transferido a {nuevo_asesor['nombre']}", "nuevo_asesor_id": nuevo_asesor_id}

# ===========================================================
#  UPDATE STATUS - LÓGICA COMPLETA (DOCTORES Y ASESORES)
# ===========================================================
def update_lead_status(conn, lead_id: int, usuario_id: int, data):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE id=%s", (lead_id,))
    lead = cur.fetchone()
    if not lead:
        cur.close()
        raise ValueError("Lead no encontrado")

    cur.execute("SELECT * FROM usuarios WHERE id=%s", (usuario_id,))
    usuario = cur.fetchone()
    if not usuario:
        cur.close()
        raise ValueError("Usuario no encontrado")

    rol = usuario["rol"]
    now = datetime.now()
    sales = lead["sales_status"] or ""
    appt = lead["appointment_status"] or ""
    med = lead["medical_status"] or ""
    updates = {}
    nota = ""
    control_id = None

    def log():
        after_s = updates.get("sales_status", sales)
        after_a = updates.get("appointment_status", appt)
        after_m = updates.get("medical_status", med)
        cur.execute(
            "INSERT INTO historial_estados (lead_id,estado_anterior,estado_nuevo,cambiado_por,comentario) "
            "VALUES (%s,%s,%s,%s,%s)",
            (lead_id, f"S:{sales}|A:{appt}|M:{med}",
             f"S:{after_s}|A:{after_a}|M:{after_m}",
             usuario_id, nota or data.comentario or "")
        )

    # ================================================================
    #  ROL: ASESOR
    # ================================================================
    if rol == "asesor":

        if data.sales_status == "Callback" and data.booked_call_fecha:
            updates["sales_status"] = "Callback"
            nota = f"Callback agendado para {data.booked_call_fecha}"
            cur.execute(
                "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
                "VALUES (%s,%s,%s,%s,%s,'Pendiente')",
                (lead_id, usuario_id, data.booked_call_fecha,
                 data.booked_call_tipo or "Llamada", data.booked_call_notas or "")
            )
            conn.commit()

        elif data.cita_confirmada is True and sales in ("Scheduled Appointment", "Rescheduled Appointment"):
                if not data.doctor_id:
                    raise ValueError("Se requiere doctor para confirmar")
                updates["cita_confirmada"] = True
                updates["appointment_status"] = "Confirmed"
                updates["doctor_id"] = data.doctor_id
                if not med:
                    updates["medical_status"] = "Pending Evaluation"
                if data.treatment_date:
                    updates["treatment_date"] = _parse_fecha(data.treatment_date)
                nota = f"Cita confirmada -> doctor id={data.doctor_id}"
                _update_agenda_estado(conn, lead_id, 'Confirmed')

        elif data.cita_confirmada is False and sales in ("Scheduled Appointment", "Rescheduled Appointment") and lead.get("cita_confirmada"):
            updates["cita_confirmada"] = False
            updates["appointment_status"] = "Scheduled"
            nota = "Cita desconfirmada por asesor"
            _update_agenda_estado(conn, lead_id, 'Scheduled')

        elif data.appointment_status == "Canceled" and sales == "Scheduled Appointment":
            updates["sales_status"] = "Cancelled Appointment"
            updates["appointment_status"] = "Canceled"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "Cita cancelada por asesor"
            _delete_from_agenda(conn, lead_id)

        elif data.appointment_status == "No Show" and sales == "Scheduled Appointment":
            updates["sales_status"] = "Cancelled Appointment"
            updates["appointment_status"] = "No Show"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "No Show marcado por asesor"
            _delete_from_agenda(conn, lead_id)

        elif data.appointment_status == "Rescheduled" and sales == "Scheduled Appointment":
            updates["sales_status"] = "Rescheduled Appointment"
            updates["appointment_status"] = "Rescheduled"
            if data.treatment_date:
                updates["treatment_date"] = _parse_fecha(data.treatment_date)
            nota = "Cita reagendada"
            _update_agenda_fecha(conn, lead_id, data.treatment_date, 'Rescheduled')

        elif data.sales_status == "Treatment in Progress" and sales == "Treatment Proposal Sent":
            if not lead.get("treatment_confirmed"):
                raise ValueError("El paciente aún no ha confirmado la propuesta de tratamiento")
            if not data.treatment_date:
                raise ValueError("Fecha tentativa de inicio obligatoria")
            updates["sales_status"] = "Treatment in Progress"
            updates["medical_status"] = "Treatment Scheduled"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            updates["treatment_date"] = _parse_fecha(data.treatment_date)
            if data.treatment_start_date:
                updates["treatment_start_date"] = _parse_fecha(data.treatment_start_date)
            if data.treatment_end_date:
                updates["treatment_end_date"] = _parse_fecha(data.treatment_end_date)
            if data.medilink_numero:
                updates["medilink_numero"] = data.medilink_numero
            if data.doctor_id:
                updates["doctor_id"] = data.doctor_id
            nota = f"Inicio de tratamiento agendado: {data.treatment_date}"
            _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id or lead.get("doctor_id"), 'Scheduled')

        elif data.cita_confirmada is True and sales == "Treatment in Progress":
            updates["cita_confirmada"] = True
            updates["appointment_status"] = "Confirmed"
            nota = "Asesor confirmó asistencia del paciente al tratamiento"
            _update_agenda_estado(conn, lead_id, 'Confirmed')

        elif data.confirm_reschedule is True and sales == "Rescheduled Appointment" and med:
            if not data.treatment_date:
                raise ValueError("Se requiere nueva fecha para confirmar reagenda")
            updates["sales_status"] = "Treatment in Progress"
            updates["medical_status"] = "Treatment Scheduled"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            updates["treatment_date"] = _parse_fecha(data.treatment_date)
            nota = f"Reagenda de tratamiento confirmada por asesor: {data.treatment_date}"
            _sync_agenda(conn, lead_id, data.treatment_date, lead.get("doctor_id"), 'Scheduled')

        elif data.sales_status == "Scheduled Appointment" and sales == "Canceled Treatment":
            if not data.medilink_numero and not lead.get("medilink_numero"):
                raise ValueError("Número de paciente (medilink) obligatorio para agendar consulta")
            updates["sales_status"] = "Scheduled Appointment"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            if data.doctor_id:
                updates["doctor_id"] = data.doctor_id
            if data.treatment_date:
                updates["treatment_date"] = _parse_fecha(data.treatment_date)
            if data.medilink_numero:
                updates["medilink_numero"] = data.medilink_numero
            nota = "Consulta reagendada desde cancelación"
            _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id, 'Scheduled')

        elif data.sales_status == "Treatment Proposal Sent" and sales == "Canceled Treatment":
            updates["sales_status"] = "Treatment Proposal Sent"
            updates["appointment_status"] = "Sent"
            nota = "Tratamiento reagendado"

        elif data.sales_status == "Callback" and sales == "Canceled Treatment":
            updates["sales_status"] = "Callback"
            nota = "Seguimiento iniciado"
            if data.booked_call_fecha:
                cur.execute(
                    "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
                    "VALUES (%s,%s,%s,%s,%s,'Pendiente')",
                    (lead_id, usuario_id, data.booked_call_fecha,
                     data.booked_call_tipo or "Llamada", data.booked_call_notas or "")
                )
                conn.commit()

        elif sales == "Treatment Proposal Sent" and data.appointment_status in ["Canceled", "No Show"]:
            updates["sales_status"] = "Canceled Treatment"
            updates["appointment_status"] = data.appointment_status
            nota = f"Tratamiento {data.appointment_status}"

        elif data.sales_status:
            nuevo = data.sales_status
            trans_validas = {
                    "New Lead":                  ["First Contact", "No Answer", "Callback", "Scheduled Appointment", "Lost"],
                    "First Contact":             ["Callback", "Scheduled Appointment", "No Answer", "Lost"],
                    "No Answer":                 ["Callback", "First Contact", "Lost", "Scheduled Appointment"],
                    "Callback":                  ["First Contact", "Scheduled Appointment", "Lost", "No Answer"],
                    "Scheduled Appointment":     ["Callback", "Lost", "No Answer", "Rescheduled Appointment", "Cancelled Appointment", "Treatment Proposal Sent"],
                    "Rescheduled Appointment":   ["Callback", "Lost", "No Answer", "Scheduled Appointment", "Cancelled Appointment"],
                    "Cancelled Appointment":     ["Scheduled Appointment", "Callback", "Lost", "No Answer"],
                }
            if sales in trans_validas:
                if nuevo == sales:
                    pass
                elif nuevo not in trans_validas[sales]:
                    raise ValueError(f"Transición no permitida: {sales} -> {nuevo}")
            else:
                permitidos = ["New Lead", "First Contact", "Callback", "No Answer", "Lost",
                              "Scheduled Appointment", "Rescheduled Appointment", "Cancelled Appointment", "Canceled Treatment"]
                if nuevo not in permitidos:
                    raise ValueError(f"No puedes mover este lead a '{nuevo}'")

            updates["sales_status"] = nuevo
            nota = f"Asesor: {sales} -> {nuevo}"

            if nuevo == "Scheduled Appointment":
                medilink = data.medilink_numero or lead.get("medilink_numero")
                if not medilink:
                    raise ValueError("Número de paciente (medilink_numero) obligatorio para agendar consulta")
                updates["appointment_status"] = "Scheduled"
                updates["medical_status"] = "Pending Evaluation"
                updates["cita_confirmada"] = False
                if data.medilink_numero:
                    updates["medilink_numero"] = data.medilink_numero
                if data.doctor_id:
                    updates["doctor_id"] = data.doctor_id
                if data.treatment_date:
                    updates["treatment_date"] = _parse_fecha(data.treatment_date)
                _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id, 'Scheduled')
            elif nuevo == "Callback" and data.booked_call_fecha:
                cur.execute(
                    "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
                    "VALUES (%s,%s,%s,%s,%s,'Pendiente')",
                    (lead_id, usuario_id, data.booked_call_fecha,
                     data.booked_call_tipo or "Llamada", data.booked_call_notas or "")
                )
                conn.commit()
                nota = f"Callback agendado para {data.booked_call_fecha}"
            elif nuevo == "Lost":
                if not data.rejection_reason:
                    raise ValueError("Se requiere razón de pérdida")
                updates["rejection_reason"] = data.rejection_reason
                updates["appointment_status"] = None
                updates["medical_status"] = None
                _delete_from_agenda(conn, lead_id)

        elif data.crear_control:
            pass
        elif not data.comentario:
            raise ValueError("No hay cambios válidos para el asesor")

    # ================================================================
    #  ROL: DOCTOR
    # ================================================================
    elif rol == "doctor":

        if data.treatment_end_date and med == "In Treatment":
            updates["treatment_end_date"] = _parse_fecha(data.treatment_end_date)
            nota = f"Fecha fin actualizada: {data.treatment_end_date}"

        elif data.appointment_status == "Canceled" and sales == "Scheduled Appointment":
            updates["sales_status"] = "Cancelled Appointment"
            updates["appointment_status"] = "Canceled"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "Cita cancelada por doctor"
            _delete_from_agenda(conn, lead_id)
            _notificar_lead_devuelto_asesor(conn, lead, "Cita cancelada por el doctor")

        elif data.appointment_status == "No Show" and sales == "Scheduled Appointment":
            updates["sales_status"] = "Cancelled Appointment"
            updates["appointment_status"] = "No Show"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "No Show marcado por doctor"
            _delete_from_agenda(conn, lead_id)
            _notificar_lead_devuelto_asesor(conn, lead, "Paciente no asistió a la cita (No Show)")

        elif data.appointment_status == "Attended" and sales == "Scheduled Appointment":
            updates["appointment_status"] = "Attended"
            if not med:
                updates["medical_status"] = "Pending Evaluation"
            nota = "Paciente asistió a consulta"
            _update_agenda_estado(conn, lead_id, 'Attended')

        elif data.treatment_confirmed is True and sales == "Treatment Proposal Sent":
            updates["treatment_confirmed"] = True
            nota = "Doctor confirmó aceptación del paciente -> asesor puede agendar inicio"

        elif data.appointment_status == "Rescheduled" and med in ("Treatment Scheduled", "In Treatment"):
            updates["sales_status"] = "Rescheduled Appointment"
            updates["appointment_status"] = "Rescheduled"
            updates["medical_status"] = None
            updates["cita_confirmada"] = False
            nota = "Tratamiento reagendado por doctor -> asesor para confirmar nueva fecha"
            _delete_from_agenda(conn, lead_id)
            _notificar_lead_devuelto_asesor(conn, lead, "Tratamiento reagendado por el doctor")

        elif data.medical_status == "In Treatment" and med == "Treatment Scheduled":
            if not data.treatment_start_date or not data.treatment_end_date:
                raise ValueError("Fechas de inicio y fin del tratamiento obligatorias")
            updates["medical_status"] = "In Treatment"
            updates["sales_status"] = "Treatment in Progress"
            updates["appointment_status"] = "Attended"
            updates["treatment_start_date"] = _parse_fecha(data.treatment_start_date)
            updates["treatment_end_date"] = _parse_fecha(data.treatment_end_date)
            nota = f"Tratamiento iniciado: {data.treatment_start_date} -> {data.treatment_end_date}"
            _update_agenda_estado(conn, lead_id, 'Attended')

        elif med == "In Treatment":
            if data.mark_treatment_completed:
                updates["medical_status"] = "Treatment Completed"
                updates["sales_status"] = "Won"
                updates["appointment_status"] = "Completed"
                updates["treatment_completed"] = True
                nota = "Tratamiento completado → Won"
                _delete_from_agenda(conn, lead_id)
            elif data.quit_reason:
                updates["sales_status"] = "Lost"
                updates["quit_reason"] = data.quit_reason
                updates["medical_status"] = None
                nota = f"Abandono: {data.quit_reason}"
                _delete_from_agenda(conn, lead_id)
            elif data.next_treatment_date:
                updates["next_treatment_date"] = _parse_fecha(data.next_treatment_date)
                nota = f"Próxima sesión: {data.next_treatment_date}"
            elif data.treatment_end_date:
                updates["treatment_end_date"] = _parse_fecha(data.treatment_end_date)
                nota = f"Fecha fin actualizada: {data.treatment_end_date}"
            elif data.appointment_status == "Rescheduled":
                updates["sales_status"] = "Rescheduled Appointment"
                updates["appointment_status"] = "Rescheduled"
                updates["medical_status"] = None
                updates["cita_confirmada"] = False
                nota = "Tratamiento reagendado por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_lead_devuelto_asesor(conn, lead, "Tratamiento reagendado por el doctor")
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "Cancelled Appointment"
                updates["medical_status"] = None
                nota = "No Show en tratamiento -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_tratamiento_cancelado_asesor(conn, lead, "Paciente no asistió al tratamiento (No Show)")
            elif data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "Cancelled Appointment"
                updates["medical_status"] = None
                nota = "Tratamiento cancelado -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_tratamiento_cancelado_asesor(conn, lead, "Tratamiento cancelado por el doctor")
            elif not data.comentario:
                raise ValueError("Indica acción para el tratamiento activo")

        elif med == "Pending Evaluation":
            if data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "Cancelled Appointment"
                updates["medical_status"] = None
                nota = "Cita cancelada por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_lead_devuelto_asesor(conn, lead, "Cita cancelada por el doctor durante evaluación")
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "Cancelled Appointment"
                updates["medical_status"] = None
                nota = "No Show en evaluación -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_lead_devuelto_asesor(conn, lead, "Paciente no asistió a evaluación (No Show)")
            elif data.medical_status == "Consultation Completed":
                updates["medical_status"] = "Consultation Completed"
                updates["appointment_status"] = "Completed"
                nota = "Consulta completada"
                _update_agenda_estado(conn, lead_id, 'Completed')
            elif data.medical_status == "Treatment Proposal Sent":
                updates["medical_status"] = "Treatment Proposal Sent"
                updates["sales_status"] = "Treatment Proposal Sent"
                updates["appointment_status"] = "Sent"
                updates["treatment_confirmed"] = False
                nota = "Propuesta enviada al paciente"
            elif data.medical_status == "Candidate Rejected":
                if not data.rejection_reason:
                    raise ValueError("Se requiere razón de rechazo")
                updates["medical_status"] = "Candidate Rejected"
                updates["rejection_reason"] = data.rejection_reason
                updates["sales_status"] = "Lost"
                nota = f"Rechazado: {data.rejection_reason}"
                _delete_from_agenda(conn, lead_id)
            elif data.medical_status:
                updates["medical_status"] = data.medical_status
                nota = f"Doctor: {med} -> {data.medical_status}"

        elif med in ("Consultation Completed", "Candidate Approved"):
            if data.medical_status == "Treatment Proposal Sent":
                updates["medical_status"] = "Treatment Proposal Sent"
                updates["sales_status"] = "Treatment Proposal Sent"
                updates["appointment_status"] = "Sent"
                updates["treatment_confirmed"] = False
                nota = "Propuesta enviada al paciente"
            elif data.medical_status == "Candidate Approved":
                updates["medical_status"] = "Candidate Approved"
                nota = "Candidato aprobado"
            elif data.medical_status == "Candidate Rejected":
                if not data.rejection_reason:
                    raise ValueError("Se requiere razón de rechazo")
                updates["medical_status"] = "Candidate Rejected"
                updates["rejection_reason"] = data.rejection_reason
                updates["sales_status"] = "Lost"
                nota = f"Rechazado: {data.rejection_reason}"
                _delete_from_agenda(conn, lead_id)
            elif data.medical_status:
                updates["medical_status"] = data.medical_status
                nota = f"Doctor actualiza: {data.medical_status}"

        elif med == "Treatment Scheduled":
            if data.medical_status == "In Treatment":
                if not data.treatment_start_date or not data.treatment_end_date:
                    raise ValueError("Fechas de inicio y fin obligatorias")
                updates["medical_status"] = "In Treatment"
                updates["sales_status"] = "Treatment in Progress"
                updates["appointment_status"] = "Attended"
                updates["treatment_start_date"] = _parse_fecha(data.treatment_start_date)
                updates["treatment_end_date"] = _parse_fecha(data.treatment_end_date)
                nota = f"Tratamiento iniciado: {data.treatment_start_date} -> {data.treatment_end_date}"
                _update_agenda_estado(conn, lead_id, 'Attended')
            elif data.appointment_status == "Rescheduled":
                updates["sales_status"] = "Rescheduled Appointment"
                updates["appointment_status"] = "Rescheduled"
                updates["medical_status"] = None
                updates["cita_confirmada"] = False
                nota = "Tratamiento reagendado por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_lead_devuelto_asesor(conn, lead, "Tratamiento reagendado por el doctor")
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "Cancelled Appointment"
                updates["medical_status"] = None
                nota = "No Show en inicio de tratamiento -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_tratamiento_cancelado_asesor(conn, lead, "Paciente no asistió al inicio de tratamiento (No Show)")
            elif data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "Cancelled Appointment"
                updates["medical_status"] = None
                nota = "Tratamiento cancelado por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
                _notificar_tratamiento_cancelado_asesor(conn, lead, "Tratamiento cancelado por el doctor")

        elif data.rejection_reason and not data.medical_status:
            updates["medical_status"] = "Candidate Rejected"
            updates["rejection_reason"] = data.rejection_reason
            updates["sales_status"] = "Lost"
            nota = f"Rechazado: {data.rejection_reason}"
            _delete_from_agenda(conn, lead_id)

        elif data.crear_control:
            pass
        elif not data.comentario:
            raise ValueError("No hay cambios válidos para el doctor")

    # ================================================================
    #  ROL: SOPORTE (acceso completo)
    # ================================================================
    elif rol == "soporte":
        if data.sales_status:                    updates["sales_status"]         = data.sales_status
        if data.appointment_status:              updates["appointment_status"]   = data.appointment_status
        if data.medical_status:                  updates["medical_status"]       = data.medical_status
        if data.doctor_id is not None:           updates["doctor_id"]            = data.doctor_id
        if data.treatment_date:                  updates["treatment_date"]       = _parse_fecha(data.treatment_date)
        if data.treatment_start_date:            updates["treatment_start_date"] = _parse_fecha(data.treatment_start_date)
        if data.treatment_end_date:              updates["treatment_end_date"]   = _parse_fecha(data.treatment_end_date)
        if data.rejection_reason:                updates["rejection_reason"]     = data.rejection_reason
        if data.next_treatment_date:             updates["next_treatment_date"]  = _parse_fecha(data.next_treatment_date)
        if data.quit_reason:                     updates["quit_reason"]          = data.quit_reason
        if data.medilink_numero:                 updates["medilink_numero"]      = data.medilink_numero
        if data.cita_confirmada is not None:     updates["cita_confirmada"]      = data.cita_confirmada
        if data.treatment_confirmed is not None: updates["treatment_confirmed"]  = data.treatment_confirmed
        if data.mark_treatment_completed is not None:
            updates["treatment_completed"] = data.mark_treatment_completed
        if hasattr(data, "pipeline") and data.pipeline:
            updates["pipeline"] = data.pipeline
        nota = "Actualización por soporte"
        if data.treatment_date and data.doctor_id and updates.get("sales_status") == "Scheduled Appointment":
            _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id, 'Scheduled')

    else:
        raise ValueError("Rol no autorizado")

    # ══════════════════════════════════════════════════════════════
    # ✅ FLAGS DE EMBUDO (NUNCA SE DESACTIVAN)
    # ══════════════════════════════════════════════════════════════
    
    # Contacto inicial - SOLO estados previos a agendar
    if updates.get("sales_status") in ("First Contact","No Answer","Callback"):
        updates["primer_contacto"] = True
        if not lead.get("fecha_primer_contacto"):
            updates["fecha_primer_contacto"] = now.strftime("%Y-%m-%d")
    
    # Cita asistida - también activa evaluacion_realizada
    if updates.get("appointment_status") == "Attended":
        updates["cita_asistida"] = True
        updates["evaluacion_realizada"] = True
        if not lead.get("fecha_cita_asistida"):
            updates["fecha_cita_asistida"] = now.strftime("%Y-%m-%d")
        if not lead.get("fecha_evaluacion"):
            updates["fecha_evaluacion"] = now.strftime("%Y-%m-%d")
    
    # Propuesta enviada - solo si ya asistió
    if updates.get("sales_status") == "Treatment Proposal Sent" or updates.get("medical_status") == "Treatment Proposal Sent":
        if lead.get("cita_asistida") or updates.get("cita_asistida"):
            updates["propuesta_enviada"] = True
            if not lead.get("fecha_propuesta_enviada"):
                updates["fecha_propuesta_enviada"] = now.strftime("%Y-%m-%d")
    
    # Propuesta aceptada - solo si ya asistió
    if updates.get("treatment_confirmed") is True:
        if lead.get("cita_asistida") or updates.get("cita_asistida"):
            updates["propuesta_aceptada"] = True
            if not lead.get("fecha_propuesta_aceptada"):
                updates["fecha_propuesta_aceptada"] = now.strftime("%Y-%m-%d")
    
    # Tratamiento iniciado - solo si ya asistió
    if updates.get("sales_status") in ("Treatment in Progress", "Won"):
        if lead.get("cita_asistida") or updates.get("cita_asistida"):
            updates["tratamiento_iniciado"] = True
            if not lead.get("fecha_tratamiento_inicio"):
                updates["fecha_tratamiento_inicio"] = now.strftime("%Y-%m-%d")
    
    # Won - solo si ya asistió
    if updates.get("sales_status") == "Won":
        if lead.get("cita_asistida") or updates.get("cita_asistida"):
            updates["tratamiento_completado"] = True
            if not lead.get("fecha_won"):
                updates["fecha_won"] = now.strftime("%Y-%m-%d")

    # ══════════════════════════════════════════════════════════════
    # ✅ FLAGS DE AGENDA (NUNCA SE DESACTIVAN)
    # ══════════════════════════════════════════════════════════════
    se_esta_agendando = False
    fecha_agenda = None
    
    if updates.get("sales_status") in ("Scheduled Appointment", "Rescheduled Appointment", "Cancelled Appointment"):
        se_esta_agendando = True
    
    if updates.get("appointment_status") in ("Scheduled", "Confirmed", "Rescheduled", "Attended"):
        se_esta_agendando = True
    
    if updates.get("cita_confirmada") is True:
        se_esta_agendando = True
    
    if hasattr(data, 'treatment_date') and data.treatment_date:
        se_esta_agendando = True
        fecha_agenda = _parse_fecha(data.treatment_date)
    
    if se_esta_agendando:
        updates["consulta_agendada"] = True
        
        if not lead.get("consulta_agendada"):
            if fecha_agenda:
                updates["primera_agenda_date"] = fecha_agenda
            elif updates.get("treatment_date"):
                updates["primera_agenda_date"] = updates["treatment_date"]
            elif lead.get("treatment_date"):
                updates["primera_agenda_date"] = _parse_fecha(lead["treatment_date"])

    # ================================================================
    #  EJECUTAR CAMBIOS
    # ================================================================
    if hasattr(data, 'last_contact_date') and data.last_contact_date:
        updates["last_contact_date"] = data.last_contact_date

    if not updates and not data.comentario and not data.crear_control:
        raise ValueError("No hay cambios para aplicar")

    if updates:
        updates["fecha_actualizacion"] = "now"
        set_parts, values = [], []
        for k, v in updates.items():
            if v == "now":
                set_parts.append(f"{k}=CURRENT_TIMESTAMP")
            else:
                set_parts.append(f"{k}=%s")
                values.append(v)
        values.append(lead_id)
        cur.execute(f"UPDATE leads SET {', '.join(set_parts)} WHERE id=%s RETURNING *", values)
        updated = cur.fetchone()
        log()
    else:
        updated = lead

    if data.comentario:
        ts = now.strftime("[%Y-%m-%d %H:%M]")
        nuevo_com = f"{ts} [{rol.upper()}] {data.comentario}"
        prev = lead.get("comentarios") or ""
        cur.execute("UPDATE leads SET comentarios=%s WHERE id=%s",
                    ((prev + "\n" + nuevo_com).strip(), lead_id))

    if data.crear_control:
        c = data.crear_control
        fecha_ctrl = c.get("fecha_control") if isinstance(c, dict) else getattr(c, 'fecha_control', None)
        tipo_ctrl  = c.get("tipo", "Control") if isinstance(c, dict) else getattr(c, 'tipo', 'Control')
        desc_ctrl  = c.get("descripcion", "") if isinstance(c, dict) else getattr(c, 'descripcion', '')
        doc_ctrl   = c.get("doctor_id") if isinstance(c, dict) else getattr(c, 'doctor_id', None)
        cur.execute(
            "INSERT INTO controles (lead_id,tipo,descripcion,fecha_control,doctor_id,asesor_id,estado) "
            "VALUES (%s,%s,%s,%s,%s,%s,'Agendado') RETURNING id",
            (lead_id, tipo_ctrl, desc_ctrl, fecha_ctrl, doc_ctrl,
             usuario_id if rol == "asesor" else None)
        )
        control_id = cur.fetchone()[0]
        nota = nota or f"Control agendado: {tipo_ctrl}"

    conn.commit()
    cur.close()
    
    # ══════════════════════════════════════════════════════════════
    # ✅ LIMPIEZA AUTOMÁTICA DE NOTIFICACIONES
    # ══════════════════════════════════════════════════════════════
    try:
        resueltas = limpiar_notificaciones_por_estado(conn, lead_id)
        if resueltas > 0:
            logger.info(f"🧹 Lead #{lead_id}: {resueltas} notificaciones resueltas automáticamente")
    except Exception as e:
        logger.error(f"❌ Error limpiando notificaciones para lead #{lead_id}: {e}")
    
    return {
        "id": updated["id"],
        "sales_status": updated.get("sales_status"),
        "appointment_status": updated.get("appointment_status"),
        "medical_status": updated.get("medical_status"),
        "treatment_confirmed": updated.get("treatment_confirmed", False),
        "message": nota,
        "control_id": control_id,
    }

# ===========================================================
#  HISTORY & CONTROLES
# ===========================================================
def get_history(conn, lead_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT h.*,u.nombre FROM historial_estados h "
        "LEFT JOIN usuarios u ON h.cambiado_por=u.id "
        "WHERE h.lead_id=%s ORDER BY h.fecha DESC", (lead_id,)
    )
    hist = cur.fetchall()
    cur.close()
    return {"historial": hist}

def get_controles(conn, lead_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT c.*,d.nombre AS doctor_nombre FROM controles c "
        "LEFT JOIN usuarios d ON c.doctor_id=d.id "
        "WHERE c.lead_id=%s ORDER BY c.fecha_creacion DESC", (lead_id,)
    )
    controles = cur.fetchall()
    cur.close()
    return {"controles": controles}

# ===========================================================
#  TOGGLE FAVORITO
# ===========================================================
def toggle_favorito(conn, lead_id: int, favorito: bool, usuario_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, favorito FROM leads WHERE id=%s", (lead_id,))
    lead = cur.fetchone()
    if not lead:
        cur.close()
        raise ValueError("Lead no encontrado")
    cur.execute("UPDATE leads SET favorito=%s, fecha_actualizacion=CURRENT_TIMESTAMP WHERE id=%s",
                (favorito, lead_id))
    accion = "⭐ Marcado como favorito" if favorito else "Quitado de favoritos"
    cur.execute(
        "INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) "
        "VALUES (%s, %s, %s, %s, %s)",
        (lead_id, f"FAV:{lead.get('favorito', False)}", f"FAV:{favorito}", usuario_id, accion)
    )
    conn.commit()
    cur.close()
    return {"message": accion, "lead_id": lead_id, "favorito": favorito}