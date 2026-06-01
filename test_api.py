from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
import hashlib

app = FastAPI(title="Patient Tracking Sheet", version="8.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ══════════════════════════════════════════════════════════════════
#  TIPOS
# ══════════════════════════════════════════════════════════════════
AppointmentStatus = Literal[
    "Scheduled", "Confirmed", "Sent", "Rescheduled",
    "Canceled", "Attended", "No Show", "Completed"
]
MedicalStatus = Literal[
    "Pending Evaluation", "Consultation Completed", "Candidate Approved",
    "Candidate Rejected", "Treatment Proposal Sent", "Treatment Scheduled",
    "In Treatment", "Treatment Completed"
]
RejectionReason = Literal[
    "No interés", "Dinero", "Cáncer o malignidad activa",
    "Infecciones sistémicas no controladas", "Falla orgánica descompensada",
    "Trastornos hematológicos severos",
    "Daño estructural avanzado o pérdida irreversible de tejido",
    "Expectativas fuera del alcance clínico",
    "Evaluación de historial clínico e imágenes"
]

# ══════════════════════════════════════════════════════════════════
#  MODELOS
# ══════════════════════════════════════════════════════════════════
class LeadCreate(BaseModel):
    nombre: str
    telefono: str
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = ""
    genero: Optional[str] = ""
    ciudad: Optional[str] = ""
    notas: Optional[str] = ""
    sales_status_inicial: Optional[str] = "New Lead"
    creado_por: Optional[str] = "api"
    asesor_id: Optional[int] = None
    doctor_id: Optional[int] = None

class UsuarioCreate(BaseModel):
    nombre: str
    email: str
    password: str
    rol: str
    telefono: Optional[str] = ""
    idiomas: Optional[str] = "spanish"

class UsuarioLogin(BaseModel):
    email: str
    password: str

class CrearControl(BaseModel):
    tipo: Optional[str] = "Control"
    fecha_control: Optional[str] = None
    doctor_id: Optional[int] = None
    descripcion: Optional[str] = ""

class UpdateStatus(BaseModel):
    lead_id: int
    usuario_id: int
    comentario: Optional[str] = ""
    sales_status: Optional[str] = None          # ✅ acepta cualquier texto
    appointment_status: Optional[AppointmentStatus] = None
    medical_status: Optional[MedicalStatus] = None
    doctor_id: Optional[int] = None
    treatment_date: Optional[str] = None
    treatment_start_date: Optional[str] = None
    treatment_end_date: Optional[str] = None
    next_treatment_date: Optional[str] = None
    medilink_numero: Optional[str] = None
    cita_confirmada: Optional[bool] = None
    rejection_reason: Optional[RejectionReason] = None
    quit_reason: Optional[str] = None
    mark_treatment_completed: Optional[bool] = None
    crear_control: Optional[dict] = None

# ══════════════════════════════════════════════════════════════════
#  DB
# ══════════════════════════════════════════════════════════════════
def get_db():
    return psycopg2.connect(
        host="localhost", port=5432, database="stemwell",
        user="crm_user", password="crm2024"
    )

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

# ══════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════
@app.post("/login")
def login(data: UsuarioLogin):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM usuarios WHERE email=%s AND password=%s AND activo=true",
                (data.email, hash_password(data.password)))
    user = cur.fetchone(); cur.close(); conn.close()
    if not user: raise HTTPException(401, "Credenciales inválidas")
    return {"id": user["id"], "nombre": user["nombre"], "email": user["email"], "rol": user["rol"]}

# ══════════════════════════════════════════════════════════════════
#  USUARIOS
# ══════════════════════════════════════════════════════════════════
@app.post("/usuarios")
def crear_usuario(data: UsuarioCreate):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO usuarios (nombre,email,password,rol,telefono,idiomas) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
        (data.nombre, data.email, hash_password(data.password), data.rol, data.telefono, data.idiomas)
    )
    res = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    return {"id": res[0]} if res else {"message": "Ya existe"}

@app.get("/usuarios")
def listar_usuarios(rol: Optional[str] = None):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    if rol:
        cur.execute("SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true AND rol=%s", (rol,))
    else:
        cur.execute("SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true")
    usuarios = cur.fetchall(); cur.close(); conn.close()
    return {"usuarios": usuarios}

@app.get("/doctores")
def listar_doctores(): return listar_usuarios(rol="doctor")

@app.get("/asesores")
def listar_asesores(): return listar_usuarios(rol="asesor")

# ══════════════════════════════════════════════════════════════════
#  LEADS — FORMATO
# ══════════════════════════════════════════════════════════════════
def format_lead(l):
    def dt(v): return str(v) if v else None
    return {
        "id": l["id"], "nombre": l["nombre"], "telefono": l["telefono"], "email": l["email"],
        "categoria": l.get("categoria") or "", "canal": l.get("canal") or "",
        "genero": l.get("genero") or "", "ciudad": l.get("ciudad") or "",
        "sales_status": l.get("sales_status"), "appointment_status": l.get("appointment_status"),
        "medical_status": l.get("medical_status"),
        "asesor_id": l.get("asesor_id"), "asesor_nombre": l.get("asesor_nombre"),
        "doctor_id": l.get("doctor_id"), "doctor_nombre": l.get("doctor_nombre"),
        "comentarios": l.get("comentarios") or "",
        "rejection_reason": l.get("rejection_reason"), "quit_reason": l.get("quit_reason"),
        "medilink_numero": l.get("medilink_numero"),
        "cita_confirmada": l.get("cita_confirmada", False),
        "treatment_date": dt(l.get("treatment_date")),
        "treatment_start_date": dt(l.get("treatment_start_date")),
        "treatment_end_date": dt(l.get("treatment_end_date")),
        "next_treatment_date": dt(l.get("next_treatment_date")),
        "treatment_completed": l.get("treatment_completed", False),
        "fecha_creacion": dt(l.get("fecha_creacion")),
        "fecha_actualizacion": dt(l.get("fecha_actualizacion")),
    }

# ══════════════════════════════════════════════════════════════════
#  LEADS — LISTAR (SIN FILTRO OCULTO PARA ASESORES)
# ══════════════════════════════════════════════════════════════════
@app.get("/leads/usuario/{usuario_id}")
def leads_por_usuario(usuario_id: int, estado: Optional[str] = None):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rol FROM usuarios WHERE id=%s", (usuario_id,))
    user = cur.fetchone()
    if not user: raise HTTPException(404, "Usuario no encontrado")
    rol = user["rol"]
    base = """
        SELECT l.*, d.nombre AS doctor_nombre, a.nombre AS asesor_nombre
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id = d.id
        LEFT JOIN usuarios a ON l.asesor_id = a.id
    """
    if rol == "asesor":
        # ✅ El asesor ve todos sus leads, sin filtro oculto
        where = """
            WHERE l.asesor_id = %s
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
    leads = cur.fetchall(); cur.close(); conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

# ══════════════════════════════════════════════════════════════════
#  LEADS — ACTUALIZAR ESTADO
# ══════════════════════════════════════════════════════════════════
@app.put("/leads/estado")
def cambiar_estado(data: UpdateStatus):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE id=%s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead: raise HTTPException(404, "Lead no encontrado")
    cur.execute("SELECT * FROM usuarios WHERE id=%s", (data.usuario_id,))
    usuario = cur.fetchone()
    if not usuario: raise HTTPException(404, "Usuario no encontrado")

    rol   = usuario["rol"]
    now   = datetime.now()
    sales = lead["sales_status"] or ""
    appt  = lead["appointment_status"] or ""
    med   = lead["medical_status"] or ""
    updates = {}
    nota = ""

    def log():
        after_s = updates.get("sales_status", sales)
        after_a = updates.get("appointment_status", appt)
        after_m = updates.get("medical_status", med)
        cur.execute(
            "INSERT INTO historial_estados (lead_id,estado_anterior,estado_nuevo,cambiado_por,comentario) "
            "VALUES (%s,%s,%s,%s,%s)",
            (data.lead_id, f"S:{sales}|A:{appt}|M:{med}",
             f"S:{after_s}|A:{after_a}|M:{after_m}", data.usuario_id, nota)
        )

    # ─────────────────────────────────────────
    #  ASESOR
    # ─────────────────────────────────────────
    if rol == "asesor":

        if data.cita_confirmada is True and sales == "Appointment Scheduled":
            if not data.doctor_id:
                raise HTTPException(400, "Se requiere doctor para confirmar")
            updates["cita_confirmada"] = True
            updates["appointment_status"] = "Confirmed"
            updates["doctor_id"] = data.doctor_id
            if not med:
                updates["medical_status"] = "Pending Evaluation"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = f"Cita confirmada → doctor id={data.doctor_id}"

        elif data.appointment_status == "Rescheduled" and sales == "Appointment Scheduled":
            updates["appointment_status"] = "Rescheduled"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = "Cita reagendada por asesor"

        elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = "Canceled"
            updates["cita_confirmada"] = False
            nota = "Cita cancelada → devuelto al asesor"

        elif data.sales_status == "scheduled treatment" and sales == "Treatment Proposal Sent":
            if not data.medilink_numero:
                raise HTTPException(400, "Número Medilink obligatorio")
            if not data.treatment_start_date or not data.treatment_end_date:
                raise HTTPException(400, "Fechas de inicio y fin del tratamiento obligatorias")
            updates["sales_status"] = "scheduled treatment"
            updates["medical_status"] = "Treatment Scheduled"
            updates["medilink_numero"] = data.medilink_numero
            updates["treatment_start_date"] = data.treatment_start_date
            updates["treatment_end_date"] = data.treatment_end_date
            nota = f"Tratamiento agendado: {data.treatment_start_date} → {data.treatment_end_date}"

        elif sales == "Treatment Proposal Sent" and data.appointment_status in ["Canceled","No Show"]:
            updates["sales_status"] = "canceled treatment"
            updates["appointment_status"] = data.appointment_status
            nota = f"Tratamiento {data.appointment_status} → devuelto al asesor"

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
                "New Lead":      ["First Contact","No Answer","Follow Up","Interested","Appointment Scheduled","Lost"],
                "First Contact": ["Follow Up","Interested","Appointment Scheduled","No Answer","Lost"],
                "No Answer":     ["Follow Up","First Contact","Lost"],
                "Follow Up":     ["Interested","Appointment Scheduled","Lost"],
                "Interested":    ["Appointment Scheduled","Follow Up","Lost"],
            }
            # ✅ Si el estado actual no está en nuestro mapa, permitimos moverlo a los estados que maneja el CRM
            if sales not in trans_validas:
                permitidos = ["New Lead","First Contact","Follow Up","Interested","Lost",
                              "Appointment Scheduled","No Answer","canceled treatment"]
                if nuevo not in permitidos:
                    raise HTTPException(400, f"No puedes mover este lead a '{nuevo}'. Estados permitidos: {', '.join(permitidos)}")
            else:
                if nuevo not in trans_validas[sales]:
                    raise HTTPException(400, f"Transición no permitida: {sales} → {nuevo}")
            updates["sales_status"] = nuevo
            nota = f"Asesor: {sales} → {nuevo}"
            if nuevo == "Appointment Scheduled":
                updates["appointment_status"] = "Scheduled"
                updates["medical_status"] = "Pending Evaluation"
                updates["cita_confirmada"] = False
                if data.doctor_id: updates["doctor_id"] = data.doctor_id
                if data.treatment_date: updates["treatment_date"] = data.treatment_date
            elif nuevo == "Lost":
                if not data.rejection_reason:
                    raise HTTPException(400, "Se requiere razón de pérdida")
                updates["rejection_reason"] = data.rejection_reason
                updates["appointment_status"] = None
                updates["medical_status"] = None

        elif data.crear_control:
            pass

        elif not data.comentario:
            raise HTTPException(400, "No hay cambios válidos para el asesor")

    # ─────────────────────────────────────────
    #  DOCTOR
    # ─────────────────────────────────────────
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
                nota = "Tratamiento completado → Won"
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
                nota = "No Show → devuelto al asesor"
            elif not data.comentario:
                raise HTTPException(400, "Indica acción para el tratamiento activo")

        elif med == "Pending Evaluation":
            if data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Cita cancelada por doctor → asesor"
            elif data.medical_status == "Consultation Completed":
                updates["medical_status"] = "Consultation Completed"
                updates["appointment_status"] = "Completed"
                nota = "Consulta completada"
            elif data.medical_status == "Treatment Proposal Sent":
                updates["medical_status"] = "Treatment Proposal Sent"
                updates["sales_status"] = "Treatment Proposal Sent"
                updates["appointment_status"] = "Sent"
                nota = "Propuesta enviada → asesor hace seguimiento"
            else:
                if data.medical_status:
                    updates["medical_status"] = data.medical_status
                    nota = f"Doctor: {med} → {data.medical_status}"

        elif med in ("Consultation Completed", "Candidate Approved"):
            if data.medical_status == "Treatment Proposal Sent":
                updates["medical_status"] = "Treatment Proposal Sent"
                updates["sales_status"] = "Treatment Proposal Sent"
                updates["appointment_status"] = "Sent"
                nota = "Propuesta enviada → asesor hace seguimiento"
            elif data.medical_status == "Candidate Approved":
                updates["medical_status"] = "Candidate Approved"
                nota = "Candidato aprobado"
            elif data.medical_status == "Candidate Rejected":
                if not data.rejection_reason:
                    raise HTTPException(400, "Se requiere razón de rechazo")
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
                nota = "No Show → devuelto al asesor"
            elif data.appointment_status == "Canceled":
                updates["appointment_status"] = "Canceled"
                updates["sales_status"] = "canceled treatment"
                updates["medical_status"] = None
                nota = "Tratamiento cancelado → devuelto al asesor"

        elif data.rejection_reason and not data.medical_status:
            updates["medical_status"] = "Candidate Rejected"
            updates["rejection_reason"] = data.rejection_reason
            updates["sales_status"] = "Lost"
            nota = f"Rechazado: {data.rejection_reason}"

        elif data.crear_control:
            pass

        elif not data.comentario:
            raise HTTPException(400, "No hay cambios válidos para el doctor")

    # ─────────────────────────────────────────
    #  SOPORTE — Control total
    # ─────────────────────────────────────────
    elif rol == "soporte":
        if data.sales_status:         updates["sales_status"]         = data.sales_status
        if data.appointment_status:   updates["appointment_status"]   = data.appointment_status
        if data.medical_status:       updates["medical_status"]       = data.medical_status
        if data.doctor_id is not None: updates["doctor_id"]           = data.doctor_id
        if data.treatment_date:       updates["treatment_date"]       = data.treatment_date
        if data.treatment_start_date: updates["treatment_start_date"] = data.treatment_start_date
        if data.treatment_end_date:   updates["treatment_end_date"]   = data.treatment_end_date
        if data.rejection_reason:     updates["rejection_reason"]     = data.rejection_reason
        if data.next_treatment_date:  updates["next_treatment_date"]  = data.next_treatment_date
        if data.quit_reason:          updates["quit_reason"]          = data.quit_reason
        if data.medilink_numero:      updates["medilink_numero"]      = data.medilink_numero
        if data.cita_confirmada is not None: updates["cita_confirmada"] = data.cita_confirmada
        if data.mark_treatment_completed is not None:
            updates["treatment_completed"] = data.mark_treatment_completed
        nota = "Actualización manual por soporte"
    else:
        raise HTTPException(403, "Rol no autorizado")

    if not updates and not data.comentario and not data.crear_control:
        raise HTTPException(400, "No hay cambios para aplicar")

    if updates:
        updates["fecha_actualizacion"] = "now"
        set_parts, values = [], []
        for k, v in updates.items():
            if v == "now":
                set_parts.append(f"{k}=CURRENT_TIMESTAMP")
            else:
                set_parts.append(f"{k}=%s")
                values.append(v)
        values.append(data.lead_id)
        cur.execute(f"UPDATE leads SET {', '.join(set_parts)} WHERE id=%s RETURNING *", values)
        updated = cur.fetchone()
        log()
    else:
        updated = lead

    if data.comentario:
        ts  = now.strftime("[%Y-%m-%d %H:%M]")
        tag = f"[{rol.upper()}]"
        nuevo_com = f"{ts} {tag} {data.comentario}"
        prev = lead.get("comentarios") or ""
        cur.execute("UPDATE leads SET comentarios=%s WHERE id=%s",
                    ((prev+"\n"+nuevo_com).strip(), data.lead_id))

    control_id = None
    if data.crear_control:
        c = data.crear_control
        fecha_ctrl = c.get("fecha_control") or None
        cur.execute(
            "INSERT INTO controles (lead_id,tipo,descripcion,fecha_control,doctor_id,asesor_id,estado) "
            "VALUES (%s,%s,%s,%s,%s,%s,'Agendado') RETURNING id",
            (data.lead_id, c.get("tipo","Control"), c.get("descripcion",""),
             fecha_ctrl, c.get("doctor_id"), data.usuario_id if rol=="asesor" else None)
        )
        control_id = cur.fetchone()[0]
        nota = nota or f"Control agendado: {c.get('tipo')}"

    conn.commit(); cur.close(); conn.close()
    return {
        "id": updated["id"],
        "sales_status": updated.get("sales_status"),
        "appointment_status": updated.get("appointment_status"),
        "medical_status": updated.get("medical_status"),
        "message": nota,
        "control_id": control_id
    }

# ══════════════════════════════════════════════════════════════════
#  CREAR LEAD
# ══════════════════════════════════════════════════════════════════
@app.post("/leads")
def crear_lead(data: LeadCreate):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    if data.email:
        cur.execute("SELECT id,nombre FROM leads WHERE email=%s AND email<>''", (data.email,))
        dup = cur.fetchone()
        if dup: raise HTTPException(400, f"Ya existe un lead con ese email: {dup['nombre']}")
    if data.telefono:
        cur.execute("SELECT id,nombre FROM leads WHERE telefono=%s AND telefono<>''", (data.telefono,))
        dup = cur.fetchone()
        if dup: raise HTTPException(400, f"Ya existe un lead con ese teléfono: {dup['nombre']}")
    cur2 = conn.cursor()
    asesor_id = data.asesor_id
    if not asesor_id:
        cur2.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
        row = cur2.fetchone()
        if row: asesor_id = row[0]
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
    conn.commit(); cur.close(); cur2.close(); conn.close()
    return {"id": lead_id, "message": "Lead creado"}

# ══════════════════════════════════════════════════════════════════
#  HISTORIAL, AGENDA, CONTROLES, GOOGLE SHEETS, HEALTH
# ══════════════════════════════════════════════════════════════════
@app.get("/leads/{lead_id}/historial")
def get_historial(lead_id: int):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT h.*,u.nombre FROM historial_estados h "
        "LEFT JOIN usuarios u ON h.cambiado_por=u.id "
        "WHERE h.lead_id=%s ORDER BY h.fecha DESC",
        (lead_id,)
    )
    hist = cur.fetchall(); cur.close(); conn.close()
    return {"historial": hist}

@app.get("/agenda")
def get_agenda():
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT
            l.id AS lead_id, l.nombre AS paciente,
            l.treatment_date AS fecha_inicio,
            l.treatment_start_date, l.treatment_end_date,
            l.sales_status, l.medical_status, l.appointment_status,
            d.nombre AS doctor_nombre, d.id AS doctor_id,
            CASE
                WHEN l.medical_status = 'In Treatment' THEN 'Tratamiento'
                WHEN l.medical_status = 'Treatment Scheduled' THEN 'Tratamiento'
                WHEN l.medical_status = 'Pending Evaluation' THEN 'Consulta'
                ELSE 'Cita'
            END AS tipo,
            COALESCE(l.appointment_status, 'Reservado') AS estado
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id = d.id
        WHERE l.doctor_id IS NOT NULL
          AND l.sales_status NOT IN ('Won','Lost')
          AND (l.treatment_date IS NOT NULL OR l.treatment_start_date IS NOT NULL)
        ORDER BY COALESCE(l.treatment_start_date, l.treatment_date) ASC
    """)
    slots = cur.fetchall(); cur.close(); conn.close()
    return {"slots": slots}

@app.get("/leads/{lead_id}/controles")
def get_controles(lead_id: int):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT c.*,d.nombre AS doctor_nombre FROM controles c "
        "LEFT JOIN usuarios d ON c.doctor_id=d.id "
        "WHERE c.lead_id=%s ORDER BY c.fecha_creacion DESC",
        (lead_id,)
    )
    controles = cur.fetchall(); cur.close(); conn.close()
    return {"controles": controles}

class LeadGoogle(BaseModel):
    nombre: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = "Website"
    source: Optional[str] = "google_sheets"

@app.post("/google/lead")
def recibir_lead_google(lead: LeadGoogle):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone(); asesor_id = row[0] if row else None
    cur.execute(
        "INSERT INTO leads (nombre,telefono,email,categoria,canal,sales_status,asesor_id,creado_por) "
        "VALUES (%s,%s,%s,%s,%s,'New Lead',%s,%s) RETURNING id",
        (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal, asesor_id, lead.source)
    )
    result = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    return {"id": result[0], "message": "Lead creado desde Google Sheets"}

@app.get("/health")
def health():
    try: conn = get_db(); conn.close(); return {"status": "ok"}
    except: return {"status": "error"}