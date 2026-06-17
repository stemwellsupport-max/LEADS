# app/services/lead_service.py
# -*- coding: utf-8 -*-
from datetime import datetime, date
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger("stemwell")

# ===========================================================
#  AUXILIARES AGENDA
# ===========================================================
def _parse_fecha(v):
    if not v: return None
    s = str(v)
    if "T" in s: return s.replace("T", " ")
    if " " in s: return s
    return s + " 00:00:00"

def _sync_agenda(conn, lead_id, treatment_date, doctor_id, estado='Scheduled'):
    if not treatment_date or not doctor_id: return
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
    cur.close()

def _delete_from_agenda(conn, lead_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM agenda_doctor WHERE lead_id=%s", (lead_id,))
    cur.close()

def _update_agenda_estado(conn, lead_id, estado):
    cur = conn.cursor()
    cur.execute("UPDATE agenda_doctor SET estado=%s, fecha_actualizacion=CURRENT_TIMESTAMP WHERE lead_id=%s",
                (estado, lead_id))
    cur.close()

def _update_agenda_fecha(conn, lead_id, treatment_date, estado='Rescheduled'):
    if not treatment_date: return
    fecha = _parse_fecha(treatment_date)
    cur = conn.cursor()
    cur.execute("""UPDATE agenda_doctor
        SET fecha_inicio=%s::timestamp, fecha_fin=%s::timestamp, estado=%s,
            fecha_actualizacion=CURRENT_TIMESTAMP
        WHERE lead_id=%s""", (fecha, fecha, estado, lead_id))
    cur.close()

# ===========================================================
#  FORMAT LEAD
# ===========================================================
def _dt(v):
    if not v: return None
    s = str(v)
    if " " in s: return s.split(" ")[0]
    if "T" in s: return s.split("T")[0]
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
        "treatment_date": _dt(l.get("treatment_date")),
        "treatment_start_date": _dt(l.get("treatment_start_date")),
        "treatment_end_date": _dt(l.get("treatment_end_date")),
        "next_treatment_date": _dt(l.get("next_treatment_date")),
        "treatment_completed": l.get("treatment_completed", False),
        "fecha_creacion": _dt(l.get("fecha_creacion")),
        "fecha_actualizacion": _dt(l.get("fecha_actualizacion")),
        "admission_date": _dt(l.get("admission_date") or l.get("fecha_creacion")),
        "last_contact_date": _dt(l.get("last_contact_date") or l.get("fecha_actualizacion")),
        "pipeline": l.get("pipeline") or "",
        "favorito": l.get("favorito", False),
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

        # --- CALLBACK (agendar llamada en booked_calls) ---
        if data.sales_status == "Callback" and data.booked_call_fecha:
            updates["sales_status"] = "Callback"
            nota = f"Callback agendado para {data.booked_call_fecha}"
            cur.execute(
                "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
                "VALUES (%s,%s,%s,%s,%s,'Pendiente')",
                (lead_id, usuario_id, data.booked_call_fecha,
                 data.booked_call_tipo or "Llamada", data.booked_call_notas or "")
            )

        # --- CONFIRMAR CITA (Appointment Scheduled -> Confirmed) ---
        elif data.cita_confirmada is True and sales == "Scheduled Appointment":
            if not data.doctor_id:
                raise ValueError("Se requiere doctor para confirmar")
            updates["cita_confirmada"] = True
            updates["appointment_status"] = "Confirmed"
            updates["doctor_id"] = data.doctor_id
            if not med:
                updates["medical_status"] = "Pending Evaluation"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = f"Cita confirmada -> doctor id={data.doctor_id}"
            _update_agenda_estado(conn, lead_id, 'Confirmed')

        # --- DESCONFIRMAR CITA ---
        elif data.cita_confirmada is False and sales == "Appointment Scheduled" and lead.get("cita_confirmada"):
            updates["cita_confirmada"] = False
            updates["appointment_status"] = "Scheduled"
            nota = "Cita desconfirmada por asesor"
            _update_agenda_estado(conn, lead_id, 'Scheduled')

        # --- CANCELAR CITA ---
        elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = "Canceled"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "Cita cancelada por asesor"
            _delete_from_agenda(conn, lead_id)

        # --- NO SHOW (asesor) ---
        elif data.appointment_status == "No Show" and sales == "Appointment Scheduled":
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = "No Show"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "No Show marcado por asesor"
            _delete_from_agenda(conn, lead_id)

        # --- REAGENDAR CONSULTA ---
        elif data.appointment_status == "Rescheduled" and sales == "Appointment Scheduled":
            updates["appointment_status"] = "Rescheduled"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = "Cita reagendada"
            _update_agenda_fecha(conn, lead_id, data.treatment_date, 'Rescheduled')

        # --- AGENDAR INICIO DE TRATAMIENTO (desde Treatment Proposal Sent confirmado) ---
        elif data.sales_status == "scheduled treatment" and sales == "Treatment Proposal Sent":
            if not lead.get("treatment_confirmed"):
                raise ValueError("El paciente aún no ha confirmado la propuesta de tratamiento")
            if not data.treatment_date:
                raise ValueError("Fecha tentativa de inicio obligatoria")
            updates["sales_status"] = "scheduled treatment"
            updates["medical_status"] = "Treatment Scheduled"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            updates["treatment_date"] = data.treatment_date
            if data.doctor_id:
                updates["doctor_id"] = data.doctor_id
            nota = f"Inicio de tratamiento agendado: {data.treatment_date}"
            _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id or lead.get("doctor_id"), 'Scheduled')

        # --- CONFIRMAR QUE EL PACIENTE VIENE AL TRATAMIENTO ---
        elif data.cita_confirmada is True and sales == "scheduled treatment":
            updates["cita_confirmada"] = True
            updates["appointment_status"] = "Confirmed"
            nota = "Asesor confirmó asistencia del paciente al tratamiento"
            _update_agenda_estado(conn, lead_id, 'Confirmed')

        # --- CONFIRMAR REAGENDA DE TRATAMIENTO (doctor marcó Rescheduled Treatment) ---
        elif data.confirm_reschedule is True and sales == "Rescheduled Treatment":
            if not data.treatment_date:
                raise ValueError("Se requiere nueva fecha para confirmar reagenda")
            updates["sales_status"] = "scheduled treatment"
            updates["medical_status"] = "Treatment Scheduled"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            updates["treatment_date"] = data.treatment_date
            nota = f"Reagenda de tratamiento confirmada por asesor: {data.treatment_date}"
            _sync_agenda(conn, lead_id, data.treatment_date, lead.get("doctor_id"), 'Scheduled')

        # --- REAGENDAR CONSULTA DESDE CANCELADO ---
        elif data.sales_status == "Appointment Scheduled" and sales == "canceled treatment":
            if not data.medilink_numero and not lead.get("medilink_numero"):
                raise ValueError("Número de paciente (medilink) obligatorio para agendar consulta")
            updates["sales_status"] = "Appointment Scheduled"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            if data.doctor_id:
                updates["doctor_id"] = data.doctor_id
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            if data.medilink_numero:
                updates["medilink_numero"] = data.medilink_numero
            nota = "Consulta reagendada desde cancelación"
            _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id, 'Scheduled')

        # --- VOLVER A TREATMENT PROPOSAL SENT DESDE CANCELADO ---
        elif data.sales_status == "Treatment Proposal Sent" and sales == "canceled treatment":
            updates["sales_status"] = "Treatment Proposal Sent"
            nota = "Tratamiento reagendado"

        # --- FOLLOW UP DESDE CANCELADO ---
        elif data.sales_status == "Follow Up" and sales == "canceled treatment":
            updates["sales_status"] = "Follow Up"
            nota = "Seguimiento iniciado"

        # --- CANCELAR PROPUESTA ENVIADA ---
        elif sales == "Treatment Proposal Sent" and data.appointment_status in ["Canceled", "No Show"]:
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = data.appointment_status
            nota = f"Tratamiento {data.appointment_status}"

        # --- TRANSICIONES GENERALES DE VENTAS ---
        elif data.sales_status:
            nuevo = data.sales_status
            trans_validas = {
                "New Lead":      ["First Contact","No Answer","Callback","Follow Up","Interested","Appointment Scheduled","Lost","At reception"],
                "First Contact": ["Follow Up","Interested","Appointment Scheduled","No Answer","Callback","Lost","At reception"],
                "No Answer":     ["Callback","Follow Up","First Contact","Lost","At reception","Appointment Scheduled"],
                "Follow Up":     ["Interested","Appointment Scheduled","Callback","Lost","At reception"],
                "Interested":    ["Appointment Scheduled","Follow Up","Callback","Lost","At reception"],
                "Callback":      ["First Contact","Follow Up","Interested","Appointment Scheduled","Lost","No Answer","At reception"],
                "At reception":  ["Appointment Scheduled","Interested","Follow Up","Callback","Lost"],
                "Appointment Scheduled": ["Callback","Follow Up","Lost","At reception"],
                "Rescheduled Appointment": ["Callback","Follow Up","Lost","At reception"],
                "Cancelled Appointment": ["Callback","Follow Up","Lost","At reception"],
            }
            if sales in trans_validas:
                if nuevo not in trans_validas[sales]:
                    raise ValueError(f"Transición no permitida: {sales} -> {nuevo}")
            else:
                permitidos = ["New Lead","First Contact","Follow Up","Interested","Lost","Appointment Scheduled","No Answer","canceled treatment","Callback","At reception","International line"]
                if nuevo not in permitidos:
                    raise ValueError(f"No puedes mover este lead a '{nuevo}'")

            updates["sales_status"] = nuevo
            nota = f"Asesor: {sales} -> {nuevo}"

            if nuevo == "Appointment Scheduled":
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
                    updates["treatment_date"] = data.treatment_date
                _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id, 'Scheduled')
            elif nuevo == "Callback" and data.booked_call_fecha:
                cur.execute(
                    "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
                    "VALUES (%s,%s,%s,%s,%s,'Pendiente')",
                    (lead_id, usuario_id, data.booked_call_fecha,
                     data.booked_call_tipo or "Llamada", data.booked_call_notas or "")
                )
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
        # (MANTENER TODO EL CÓDIGO DEL DOCTOR IGUAL - sin cambios)
        if data.treatment_end_date and med == "In Treatment":
            updates["treatment_end_date"] = data.treatment_end_date
            nota = f"Fecha fin actualizada: {data.treatment_end_date}"
        elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = "Canceled"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "Cita cancelada por doctor"
            _delete_from_agenda(conn, lead_id)
        elif data.appointment_status == "No Show" and sales == "Appointment Scheduled":
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = "No Show"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "No Show marcado por doctor"
            _delete_from_agenda(conn, lead_id)
        elif data.appointment_status == "Attended" and sales == "Appointment Scheduled":
            updates["appointment_status"] = "Attended"
            if not med:
                updates["medical_status"] = "Pending Evaluation"
            nota = "Paciente asistió a consulta"
            _update_agenda_estado(conn, lead_id, 'Attended')
        elif data.treatment_confirmed is True and sales == "Treatment Proposal Sent":
            updates["treatment_confirmed"] = True
            nota = "Doctor confirmó aceptación del paciente -> asesor puede agendar inicio"
        elif data.appointment_status == "Rescheduled" and med in ("Treatment Scheduled", "In Treatment"):
            updates["sales_status"] = "Rescheduled Treatment"
            updates["appointment_status"] = "Rescheduled"
            updates["medical_status"] = None
            updates["cita_confirmada"] = False
            nota = "Tratamiento reagendado por doctor -> asesor para confirmar nueva fecha"
            _delete_from_agenda(conn, lead_id)
        elif data.medical_status == "In Treatment" and med == "Treatment Scheduled":
            if not data.treatment_start_date or not data.treatment_end_date:
                raise ValueError("Fechas de inicio y fin del tratamiento obligatorias")
            updates["medical_status"] = "In Treatment"
            updates["appointment_status"] = "Attended"
            updates["treatment_start_date"] = data.treatment_start_date
            updates["treatment_end_date"] = data.treatment_end_date
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
                updates["next_treatment_date"] = data.next_treatment_date
                nota = f"Próxima sesión: {data.next_treatment_date}"
            elif data.treatment_end_date:
                updates["treatment_end_date"] = data.treatment_end_date
                nota = f"Fecha fin actualizada: {data.treatment_end_date}"
            elif data.appointment_status == "Rescheduled":
                updates["sales_status"] = "Rescheduled Treatment"
                updates["appointment_status"] = "Rescheduled"
                updates["medical_status"] = None
                updates["cita_confirmada"] = False
                nota = "Tratamiento reagendado por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "No Show en tratamiento -> asesor"
                _delete_from_agenda(conn, lead_id)
            elif data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Tratamiento cancelado -> asesor"
                _delete_from_agenda(conn, lead_id)
            elif not data.comentario:
                raise ValueError("Indica acción para el tratamiento activo")
        elif med == "Pending Evaluation":
            if data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Cita cancelada por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
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
            elif data.medical_status == "Highly Interested":
                updates["medical_status"] = "Highly Interested"
                updates["sales_status"] = "Follow Up"
                nota = "Paciente muy interesado -> asesor para seguimiento"
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
            elif data.medical_status == "Highly Interested":
                updates["medical_status"] = "Highly Interested"
                updates["sales_status"] = "Follow Up"
                nota = "Paciente muy interesado -> asesor para seguimiento"
            elif data.medical_status:
                updates["medical_status"] = data.medical_status
                nota = f"Doctor actualiza: {data.medical_status}"
        elif med == "Treatment Scheduled":
            if data.medical_status == "In Treatment":
                if not data.treatment_start_date or not data.treatment_end_date:
                    raise ValueError("Fechas de inicio y fin obligatorias")
                updates["medical_status"] = "In Treatment"
                updates["appointment_status"] = "Attended"
                updates["treatment_start_date"] = data.treatment_start_date
                updates["treatment_end_date"] = data.treatment_end_date
                nota = f"Tratamiento iniciado: {data.treatment_start_date} -> {data.treatment_end_date}"
                _update_agenda_estado(conn, lead_id, 'Attended')
            elif data.appointment_status == "Rescheduled":
                updates["sales_status"] = "Rescheduled Treatment"
                updates["appointment_status"] = "Rescheduled"
                updates["medical_status"] = None
                updates["cita_confirmada"] = False
                nota = "Tratamiento reagendado por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "No Show en inicio de tratamiento -> asesor"
                _delete_from_agenda(conn, lead_id)
            elif data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Tratamiento cancelado por doctor -> asesor"
                _delete_from_agenda(conn, lead_id)
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
        if data.treatment_date:                  updates["treatment_date"]       = data.treatment_date
        if data.treatment_start_date:            updates["treatment_start_date"] = data.treatment_start_date
        if data.treatment_end_date:              updates["treatment_end_date"]   = data.treatment_end_date
        if data.rejection_reason:                updates["rejection_reason"]     = data.rejection_reason
        if data.next_treatment_date:             updates["next_treatment_date"]  = data.next_treatment_date
        if data.quit_reason:                     updates["quit_reason"]          = data.quit_reason
        if data.medilink_numero:                 updates["medilink_numero"]      = data.medilink_numero
        if data.cita_confirmada is not None:     updates["cita_confirmada"]      = data.cita_confirmada
        if data.treatment_confirmed is not None: updates["treatment_confirmed"]  = data.treatment_confirmed
        if data.mark_treatment_completed is not None:
            updates["treatment_completed"] = data.mark_treatment_completed
        nota = "Actualización por soporte"
        if data.treatment_date and data.doctor_id and updates.get("sales_status") == "Appointment Scheduled":
            _sync_agenda(conn, lead_id, data.treatment_date, data.doctor_id, 'Scheduled')

    else:
        raise ValueError("Rol no autorizado")

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
    """Activa/desactiva favorito y registra en historial"""
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