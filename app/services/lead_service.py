from datetime import datetime, date
from psycopg2.extras import RealDictCursor
from ..models.schemas import UpdateStatus, LeadCreate


# ─────────────────────────────────────────
#  SEMÁFORO
# ─────────────────────────────────────────
def calc_semaforo(lead):
    """
    🎉 si Won
    ""  si Lost
    ?   si no hay fecha de último contacto
    🟢  <= 1 día sin contacto
    🟡  <= 2 días sin contacto
    🔴  > 2 días sin contacto
    """
    sales = (lead.get("sales_status") or "").lower()
    if "won" in sales:
        return "🎉"
    if "lost" in sales:
        return ""

    last = lead.get("last_contact_date") or lead.get("fecha_actualizacion")
    if not last:
        return "?"

    if isinstance(last, datetime):
        last = last.date()
    elif isinstance(last, str):
        try:
            # Intentar parsear fecha (puede venir con o sin hora)
            last = datetime.fromisoformat(last[:10].replace(" ", "T")).date()
        except Exception:
            return "?"

    dias = (date.today() - last).days
    if dias <= 1:
        return "🟢"
    elif dias <= 2:
        return "🟡"
    else:
        return "🔴"


# ─────────────────────────────────────────
#  FORMAT LEAD
# ─────────────────────────────────────────
def format_lead(l):
    def dt(v):
        if not v:
            return None
        s = str(v)
        # Si tiene hora, tomar solo la fecha
        if " " in s:
            return s.split(" ")[0]
        if "T" in s:
            return s.split("T")[0]
        return s

    return {
        "id": l["id"],
        "nombre": l["nombre"],
        "telefono": l["telefono"],
        "email": l["email"],
        "categoria": l.get("categoria") or "",
        "canal": l.get("canal") or "",
        "genero": l.get("genero") or "",
        "ciudad": l.get("ciudad") or "",
        "sales_status": l.get("sales_status"),
        "appointment_status": l.get("appointment_status"),
        "medical_status": l.get("medical_status"),
        "asesor_id": l.get("asesor_id"),
        "asesor_nombre": l.get("asesor_nombre"),
        "doctor_id": l.get("doctor_id"),
        "doctor_nombre": l.get("doctor_nombre"),
        "comentarios": l.get("comentarios") or "",
        "rejection_reason": l.get("rejection_reason"),
        "quit_reason": l.get("quit_reason"),
        "medilink_numero": l.get("medilink_numero"),
        "cita_confirmada": l.get("cita_confirmada", False),
        "treatment_date": dt(l.get("treatment_date")),
        "treatment_start_date": dt(l.get("treatment_start_date")),
        "treatment_end_date": dt(l.get("treatment_end_date")),
        "next_treatment_date": dt(l.get("next_treatment_date")),
        "treatment_completed": l.get("treatment_completed", False),
        "fecha_creacion": dt(l.get("fecha_creacion")),
        "fecha_actualizacion": dt(l.get("fecha_actualizacion")),
        # NUEVOS CAMPOS
        "admission_date": dt(l.get("admission_date") or l.get("fecha_creacion")),
        "last_contact_date": dt(l.get("last_contact_date") or l.get("fecha_actualizacion")),
        "first_contact": l.get("first_contact") or "",           # <- TEXTO (nombre de quien contactó)
        "semaforo": l.get("semaforo") or calc_semaforo(l),       # <- calculado si no viene de BD
    }


# ─────────────────────────────────────────
#  GET LEADS FOR USER
# ─────────────────────────────────────────
def get_leads_for_user(conn, usuario_id: int, estado: str = None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rol FROM usuarios WHERE id=%s", (usuario_id,))
    user = cur.fetchone()
    if not user:
        cur.close()
        raise ValueError("Usuario no encontrado")
    rol = user["rol"]

    base = """
        SELECT l.*, d.nombre AS doctor_nombre, a.nombre AS asesor_nombre
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id = d.id
        LEFT JOIN usuarios a ON l.asesor_id = a.id
    """

    if rol == "asesor":
        where = """
            WHERE l.asesor_id = %s
            AND NOT (
                (l.sales_status = 'Appointment Scheduled' AND l.cita_confirmada = true
                 AND l.medical_status IN ('Pending Evaluation','Consultation Completed','Candidate Approved'))
                OR
                (l.sales_status = 'scheduled treatment'
                 AND l.medical_status IN ('Treatment Scheduled','In Treatment'))
            )
        """
        params = [usuario_id]
        if estado:
            where += " AND l.sales_status = %s"
            params.append(estado)
    elif rol == "doctor":
        where = """
            WHERE l.doctor_id = %s
            AND l.medical_status IS NOT NULL
            AND l.medical_status NOT IN ('Treatment Completed','Candidate Rejected')
        """
        params = [usuario_id]
        if estado:
            where = "WHERE l.doctor_id = %s AND l.medical_status = %s"
            params = [usuario_id, estado]
    else:  # soporte
        where = "WHERE 1=1"
        params = []
        if estado:
            where += " AND (l.sales_status=%s OR l.medical_status=%s)"
            params = [estado, estado]

    cur.execute(base + where + " ORDER BY l.fecha_actualizacion DESC", params)
    leads = cur.fetchall()
    cur.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}


# ─────────────────────────────────────────
#  CREATE LEAD
# ─────────────────────────────────────────
def create_lead(conn, data: LeadCreate):
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
        if row:
            asesor_id = row[0]
    cur2.execute(
        "INSERT INTO leads (nombre,telefono,email,categoria,canal,genero,ciudad,notas,"
        "sales_status,asesor_id,doctor_id,creado_por) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (data.nombre, data.telefono, data.email, data.categoria, data.canal,
         data.genero, data.ciudad, data.notas,
         data.sales_status_inicial or "New Lead",
         asesor_id, data.doctor_id, data.creado_por)
    )
    lead_id = cur2.fetchone()[0]
    conn.commit()
    cur.close()
    cur2.close()
    return lead_id


# ─────────────────────────────────────────
#  UPDATE LEAD STATUS
# ─────────────────────────────────────────
def update_lead_status(conn, lead_id: int, usuario_id: int, data: UpdateStatus):
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
        "INSERT INTO historial_estados (lead_id,estado_anterior,estado_nuevo) "
        "VALUES (%s,%s,%s)",
        (lead_id, f"S:{sales}|A:{appt}|M:{med}",
        f"S:{after_s}|A:{after_a}|M:{after_m}")
)

    # ─── ASESOR ───
    if rol == "asesor":
        if data.cita_confirmada is True and sales == "Appointment Scheduled":
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

        elif data.appointment_status == "Rescheduled" and sales == "Appointment Scheduled":
            updates["appointment_status"] = "Rescheduled"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = "Cita reagendada por asesor"

        elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = "Canceled"
            updates["cita_confirmada"] = False
            updates["medical_status"] = None
            nota = "Cita cancelada -> devuelto al asesor"

        elif data.sales_status == "scheduled treatment" and sales == "Treatment Proposal Sent":
            if not data.medilink_numero:
                raise ValueError("Número Medilink obligatorio")
            if not data.treatment_start_date or not data.treatment_end_date:
                raise ValueError("Fechas de inicio y fin del tratamiento obligatorias")
            updates["sales_status"] = "scheduled treatment"
            updates["medical_status"] = "Treatment Scheduled"
            updates["medilink_numero"] = data.medilink_numero
            updates["treatment_start_date"] = data.treatment_start_date
            updates["treatment_end_date"] = data.treatment_end_date
            nota = f"Tratamiento agendado: {data.treatment_start_date} -> {data.treatment_end_date}"

        elif sales == "Treatment Proposal Sent" and data.appointment_status in ["Canceled", "No Show"]:
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = data.appointment_status
            nota = f"Tratamiento {data.appointment_status} -> devuelto al asesor"

        elif data.sales_status == "Appointment Scheduled" and sales == "canceled treatment":
            updates["sales_status"] = "Appointment Scheduled"
            updates["appointment_status"] = "Scheduled"
            updates["cita_confirmada"] = False
            if data.doctor_id: updates["doctor_id"] = data.doctor_id
            if data.treatment_date: updates["treatment_date"] = data.treatment_date
            nota = "Consulta reagendada desde cancelación"

        elif data.sales_status == "Treatment Proposal Sent" and sales == "canceled treatment":
            updates["sales_status"] = "Treatment Proposal Sent"
            nota = "Tratamiento reagendado"

        elif data.sales_status == "Follow Up" and sales == "canceled treatment":
            updates["sales_status"] = "Follow Up"
            nota = "Seguimiento iniciado"

        elif data.sales_status:
            nuevo = data.sales_status
            trans_validas = {
                "New Lead":      ["First Contact", "No Answer", "Follow Up", "Interested", "Appointment Scheduled", "Lost"],
                "First Contact": ["Follow Up", "Interested", "Appointment Scheduled", "No Answer", "Lost"],
                "No Answer":     ["Follow Up", "First Contact", "Lost"],
                "Follow Up":     ["Interested", "Appointment Scheduled", "Lost"],
                "Interested":    ["Appointment Scheduled", "Follow Up", "Lost"],
            }
            if nuevo not in trans_validas.get(sales, []):
                raise ValueError(f"Transición no permitida: {sales} -> {nuevo}")
            updates["sales_status"] = nuevo
            nota = f"Asesor: {sales} -> {nuevo}"
            if nuevo == "Appointment Scheduled":
                updates["appointment_status"] = "Scheduled"
                updates["medical_status"] = "Pending Evaluation"
                updates["cita_confirmada"] = False
                if data.doctor_id: updates["doctor_id"] = data.doctor_id
                if data.treatment_date: updates["treatment_date"] = data.treatment_date
            elif nuevo == "Lost":
                if not data.rejection_reason:
                    raise ValueError("Se requiere razón de pérdida")
                updates["rejection_reason"] = data.rejection_reason
                updates["appointment_status"] = None
                updates["medical_status"] = None

        elif data.crear_control:
            pass

        elif not data.comentario:
            raise ValueError("No hay cambios válidos para el asesor")

    # ─── DOCTOR ───
    elif rol == "doctor":
        if data.treatment_end_date and med == "In Treatment":
            updates["treatment_end_date"] = data.treatment_end_date
            nota = f"Fecha fin actualizada: {data.treatment_end_date}"

        elif med == "In Treatment":
            if data.mark_treatment_completed:
                updates["medical_status"] = "Treatment Completed"
                updates["sales_status"] = "Won"
                updates["appointment_status"] = "Completed"
                updates["treatment_completed"] = True
                nota = "Tratamiento completado -> Won"
            elif data.quit_reason:
                updates["sales_status"] = "Lost"
                updates["quit_reason"] = data.quit_reason
                updates["medical_status"] = None
                nota = f"Abandono: {data.quit_reason}"
            elif data.next_treatment_date:
                updates["next_treatment_date"] = data.next_treatment_date
                nota = f"Próxima sesión: {data.next_treatment_date}"
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "No Show -> devuelto al asesor"
            elif not data.comentario:
                raise ValueError("Indica acción para el tratamiento activo")

        elif med == "Pending Evaluation":
            if data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Cita cancelada por doctor -> asesor"
            elif data.medical_status == "Consultation Completed":
                updates["medical_status"] = "Consultation Completed"
                updates["appointment_status"] = "Completed"
                nota = "Consulta completada"
            elif data.medical_status == "Treatment Proposal Sent":
                updates["medical_status"] = "Treatment Proposal Sent"
                updates["sales_status"] = "Treatment Proposal Sent"
                updates["appointment_status"] = "Sent"
                nota = "Propuesta enviada -> asesor hace seguimiento"
            else:
                if data.medical_status:
                    updates["medical_status"] = data.medical_status
                    nota = f"Doctor: {med} -> {data.medical_status}"

        elif med in ("Consultation Completed", "Candidate Approved"):
            if data.medical_status == "Treatment Proposal Sent":
                updates["medical_status"] = "Treatment Proposal Sent"
                updates["sales_status"] = "Treatment Proposal Sent"
                updates["appointment_status"] = "Sent"
                nota = "Propuesta enviada -> asesor hace seguimiento"
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
            elif data.medical_status:
                updates["medical_status"] = data.medical_status
                nota = f"Doctor actualiza estado: {data.medical_status}"

        elif med == "Treatment Scheduled":
            if data.medical_status == "In Treatment":
                updates["medical_status"] = "In Treatment"
                updates["appointment_status"] = "Attended"
                nota = "Tratamiento iniciado"
            elif data.appointment_status == "No Show":
                updates["appointment_status"] = "No Show"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "No Show -> devuelto al asesor"
            elif data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Tratamiento cancelado -> devuelto al asesor"

        elif data.rejection_reason and not data.medical_status:
            updates["medical_status"] = "Candidate Rejected"
            updates["rejection_reason"] = data.rejection_reason
            updates["sales_status"] = "Lost"
            nota = f"Rechazado: {data.rejection_reason}"

        elif data.crear_control:
            pass

        elif not data.comentario:
            raise ValueError("No hay cambios válidos para el doctor")

    # ─── SOPORTE ───
    elif rol == "soporte":
        if data.sales_status:          updates["sales_status"]         = data.sales_status
        if data.appointment_status:    updates["appointment_status"]   = data.appointment_status
        if data.medical_status:        updates["medical_status"]       = data.medical_status
        if data.doctor_id is not None: updates["doctor_id"]            = data.doctor_id
        if data.treatment_date:        updates["treatment_date"]       = data.treatment_date
        if data.treatment_start_date:  updates["treatment_start_date"] = data.treatment_start_date
        if data.treatment_end_date:    updates["treatment_end_date"]   = data.treatment_end_date
        if data.rejection_reason:      updates["rejection_reason"]     = data.rejection_reason
        if data.next_treatment_date:   updates["next_treatment_date"]  = data.next_treatment_date
        if data.quit_reason:           updates["quit_reason"]          = data.quit_reason
        if data.medilink_numero:       updates["medilink_numero"]      = data.medilink_numero
        if data.cita_confirmada is not None:
            updates["cita_confirmada"] = data.cita_confirmada
        if data.mark_treatment_completed is not None:
            updates["treatment_completed"] = data.mark_treatment_completed
            # Si soporte cancela la cita, limpiar medical_status inconsistente
        if data.appointment_status == "Canceled":
            updates["medical_status"] = None
            updates["cita_confirmada"] = False
            nota = "Actualización manual por soporte"
    else:
        raise ValueError("Rol no autorizado")

    # ─── EJECUTAR UPDATE ───
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
        tag = f"[{rol.upper()}]"
        nuevo_com = f"{ts} {tag} {data.comentario}"
        prev = lead.get("comentarios") or ""
        cur.execute("UPDATE leads SET comentarios=%s WHERE id=%s",
                    ((prev + "\n" + nuevo_com).strip(), lead_id))

    if data.crear_control:
        c = data.crear_control
        fecha_ctrl = c.get("fecha_control") or None
        cur.execute(
            "INSERT INTO controles (lead_id,tipo,descripcion,fecha_control,doctor_id,asesor_id,estado) "
            "VALUES (%s,%s,%s,%s,%s,%s,'Agendado') RETURNING id",
            (lead_id, c.get("tipo", "Control"), c.get("descripcion", ""),
             fecha_ctrl, c.get("doctor_id"), usuario_id if rol == "asesor" else None)
        )
        control_id = cur.fetchone()[0]
        nota = nota or f"Control agendado: {c.get('tipo')}"

    conn.commit()
    cur.close()
    return {
        "id": updated["id"],
        "sales_status": updated.get("sales_status"),
        "appointment_status": updated.get("appointment_status"),
        "medical_status": updated.get("medical_status"),
        "message": nota,
        "control_id": control_id
    }


# ─────────────────────────────────────────
#  GET HISTORY
# ─────────────────────────────────────────
def get_history(conn, lead_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
    "SELECT h.* FROM historial_estados h "
    "WHERE h.lead_id=%s ORDER BY h.fecha DESC",
    (lead_id,)
)
    hist = cur.fetchall()
    cur.close()
    return {"historial": hist}