from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
import hashlib

app = FastAPI(title="CRM Stemwell API", version="6.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════════
#  TIPOS
# ══════════════════════════════════════════════════════════════════
SalesStatus = Literal[
    "New Lead", "First Contact", "No Answer", "Follow Up", "Interested",
    "Appointment Scheduled",          # Asesor agenda consulta → espera confirmar
    "Treatment Follow-Up",            # Vuelve al asesor después de propuesta médica
    "Treatment Confirmed",            # Asesor confirma aceptación de tratamiento
    "scheduled treatment",            # Asesor agenda fecha de tratamiento
    "canceled treatment",             # Cita/tratamiento cancelado → asesor reagenda
    "Won",                            # Tratamiento completado
    "Lost"
]

AppointmentStatus = Literal[
    "Scheduled",       # Agendada por asesor (pendiente confirmación)
    "Confirmed",       # Asesor confirma → pasa a médico
    "Sent",            # Propuesta de tratamiento enviada al paciente
    "Rescheduled",     # Reagendada
    "Canceled",        # Cancelada
    "Attended",        # Asistió
    "No Show",         # No se presentó
]

MedicalStatus = Literal[
    "Pending Evaluation",        # Auto al confirmar cita consulta
    "Consultation Completed",    # Médico atendió consulta
    "Candidate Approved",        # Médico aprueba candidato
    "Candidate Rejected",        # Médico rechaza → Lost automático
    "Treatment Proposal Sent",   # Médico envía propuesta → vuelve al asesor
    "Treatment Scheduled",       # Asesor confirmó fecha → médico ve agendado
    "In Treatment",              # Médico inicia tratamiento
    "Treatment Completed",       # Médico finaliza → Won automático
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
    creado_por: Optional[str] = "api"
    asesor_id: Optional[int] = None
    doctor_id: Optional[int] = None

class LeadGoogle(BaseModel):
    nombre: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = "Website"
    source: Optional[str] = "google_sheets"

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

class UpdateStatus(BaseModel):
    lead_id: int
    usuario_id: int
    comentario: Optional[str] = ""
    # Campos que puede enviar el frontend
    sales_status: Optional[SalesStatus] = None
    appointment_status: Optional[AppointmentStatus] = None
    medical_status: Optional[MedicalStatus] = None
    doctor_id: Optional[int] = None
    treatment_date: Optional[str] = None           # fecha consulta o tratamiento
    next_treatment_date: Optional[str] = None       # próxima sesión In Treatment
    rejection_reason: Optional[RejectionReason] = None
    quit_reason: Optional[str] = None              # abandono de tratamiento
    mark_treatment_completed: Optional[bool] = None  # True=completado, False=siguiente sesión

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
    hashed = hash_password(data.password)
    cur.execute("SELECT * FROM usuarios WHERE email=%s AND password=%s AND activo=true", (data.email, hashed))
    user = cur.fetchone()
    cur.close(); conn.close()
    if not user:
        raise HTTPException(401, "Credenciales inválidas")
    return {"id": user["id"], "nombre": user["nombre"], "email": user["email"], "rol": user["rol"]}

# ══════════════════════════════════════════════════════════════════
#  USUARIOS
# ══════════════════════════════════════════════════════════════════
@app.post("/usuarios")
def crear_usuario(data: UsuarioCreate):
    conn = get_db(); cur = conn.cursor()
    hashed = hash_password(data.password)
    cur.execute(
        "INSERT INTO usuarios (nombre, email, password, rol, telefono, idiomas) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
        (data.nombre, data.email, hashed, data.rol, data.telefono, data.idiomas)
    )
    res = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    return {"id": res[0]} if res else {"message": "Ya existe"}

@app.get("/usuarios")
def listar_usuarios(rol: Optional[str] = None):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    if rol:
        cur.execute("SELECT id, nombre, email, rol, telefono FROM usuarios WHERE activo=true AND rol=%s", (rol,))
    else:
        cur.execute("SELECT id, nombre, email, rol, telefono FROM usuarios WHERE activo=true")
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
    return {
        "id": l["id"],
        "nombre": l["nombre"],
        "telefono": l["telefono"],
        "email": l["email"],
        "categoria": l.get("categoria") or "",
        "canal": l.get("canal") or "",
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
        "treatment_date": str(l["treatment_date"]) if l.get("treatment_date") else None,
        "next_treatment_date": str(l["next_treatment_date"]) if l.get("next_treatment_date") else None,
        "treatment_completed": l.get("treatment_completed", False),
        "fecha_creacion": str(l["fecha_creacion"]) if l.get("fecha_creacion") else None,
        "fecha_actualizacion": str(l["fecha_actualizacion"]) if l.get("fecha_actualizacion") else None,
    }

# ══════════════════════════════════════════════════════════════════
#  LEADS — LISTAR
# ══════════════════════════════════════════════════════════════════
@app.get("/leads/usuario/{usuario_id}")
def leads_por_usuario(usuario_id: int, estado: Optional[str] = None):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT rol FROM usuarios WHERE id=%s", (usuario_id,))
    user = cur.fetchone()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")

    rol = user["rol"]

    base = """
        SELECT l.*,
               d.nombre AS doctor_nombre,
               a.nombre AS asesor_nombre
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id = d.id
        LEFT JOIN usuarios a ON l.asesor_id = a.id
    """

    if rol == "asesor":
        # El asesor ve sus leads EXCEPTO los que están "en manos del médico":
        # un lead está en manos del médico cuando:
        #   - appointment_status = 'Confirmed' Y sales_status = 'Appointment Scheduled'
        #   - medical_status = 'Treatment Scheduled' Y sales_status = 'scheduled treatment'
        #   - medical_status = 'In Treatment'
        # En esos estados el lead desaparece del asesor, EXCEPTO si vuelve (Treatment Follow-Up, canceled treatment, Won, Lost)
        where = """
            WHERE l.asesor_id = %s
            AND NOT (
                -- En consulta confirmada con médico
                (l.sales_status = 'Appointment Scheduled' AND l.appointment_status = 'Confirmed')
                OR
                -- En tratamiento agendado con médico
                (l.sales_status = 'scheduled treatment' AND l.medical_status = 'Treatment Scheduled')
                OR
                -- En tratamiento activo (pero SÍ aparece en asesor como info)
                -- Descomentarr la siguiente línea si quieres que In Treatment desaparezca del asesor:
                -- (l.medical_status = 'In Treatment')
                -- Por ahora In Treatment SÍ aparece en el asesor (modo informativo)
                (1=0)
            )
        """
        params = [usuario_id]
        if estado:
            where += " AND l.sales_status = %s"
            params.append(estado)

    elif rol == "doctor":
        # El doctor ve SOLO los leads asignados a él
        # y que estén en fases médicas activas
        where = """
            WHERE l.doctor_id = %s
            AND l.medical_status IS NOT NULL
            AND l.medical_status NOT IN ('Treatment Completed', 'Candidate Rejected')
        """
        # Incluir Completed/Rejected si se filtra explícitamente
        params = [usuario_id]
        if estado:
            where = "WHERE l.doctor_id = %s AND l.medical_status = %s"
            params = [usuario_id, estado]

    else:  # soporte ve todo
        where = "WHERE 1=1"
        params = []
        if estado:
            where += " AND (l.sales_status = %s OR l.medical_status = %s)"
            params = [estado, estado]

    query = base + where + " ORDER BY l.fecha_actualizacion DESC"
    cur.execute(query, params)
    leads = cur.fetchall()
    cur.close(); conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

# ══════════════════════════════════════════════════════════════════
#  LEADS — ACTUALIZAR ESTADO
# ══════════════════════════════════════════════════════════════════
@app.put("/leads/estado")
def cambiar_estado(data: UpdateStatus):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM leads WHERE id=%s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(404, "Lead no encontrado")

    cur.execute("SELECT * FROM usuarios WHERE id=%s", (data.usuario_id,))
    usuario = cur.fetchone()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    rol = usuario["rol"]
    now = datetime.now()

    # Estado actual del lead
    sales  = lead["sales_status"]   or ""
    appt   = lead["appointment_status"] or ""
    med    = lead["medical_status"]  or ""

    updates = {}
    nota    = ""

    def log(extra=""):
        after_s = updates.get("sales_status",  sales)
        after_a = updates.get("appointment_status", appt)
        after_m = updates.get("medical_status", med)
        cur.execute(
            "INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                data.lead_id,
                f"S:{sales}|A:{appt}|M:{med}",
                f"S:{after_s}|A:{after_a}|M:{after_m}",
                data.usuario_id,
                extra
            )
        )

    # ─────────────────────────────────────────
    #  ASESOR
    # ─────────────────────────────────────────
    if rol == "asesor":

        # ── Caso especial: confirmar cita de consulta ──
        # El asesor envía appointment_status="Confirmed" + doctor_id
        if data.appointment_status == "Confirmed" and sales == "Appointment Scheduled":
            if not data.doctor_id:
                raise HTTPException(400, "Se requiere doctor_id para confirmar cita")
            updates["appointment_status"] = "Confirmed"
            updates["doctor_id"]          = data.doctor_id
            if not med:
                updates["medical_status"] = "Pending Evaluation"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = f"Cita confirmada → asignada al doctor id={data.doctor_id}"

        # ── Caso: cancelar cita de consulta pendiente ──
        elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
            updates["sales_status"]       = "canceled treatment"
            updates["appointment_status"] = "Canceled"
            nota = "Cita de consulta cancelada por asesor"

        # ── Caso: reagendar cita pendiente ──
        elif data.appointment_status == "Rescheduled" and sales == "Appointment Scheduled":
            updates["appointment_status"] = "Rescheduled"
            if data.treatment_date:
                updates["treatment_date"] = data.treatment_date
            nota = "Cita reagendada por asesor"

        # ── Transiciones normales de sales_status ──
        elif data.sales_status:
            nuevo = data.sales_status
            transiciones_validas = {
                "New Lead":            ["First Contact","No Answer","Follow Up","Interested","Appointment Scheduled","Lost"],
                "First Contact":       ["Follow Up","Interested","Appointment Scheduled","No Answer","Lost"],
                "No Answer":           ["Follow Up","First Contact","Lost"],
                "Follow Up":           ["Interested","Appointment Scheduled","Lost"],
                "Interested":          ["Appointment Scheduled","Follow Up","Lost"],
                "Appointment Scheduled": [],  # solo via appointment_status=Confirmed
                "Treatment Follow-Up": ["Treatment Confirmed","Lost"],
                "Treatment Confirmed": ["scheduled treatment","Lost"],
                "scheduled treatment": ["canceled treatment","Lost"],
                "canceled treatment":  ["Treatment Follow-Up","Follow Up","Lost"],
                "Won": [], "Lost": []
            }
            if nuevo not in transiciones_validas.get(sales, []):
                raise HTTPException(400, f"Transición no permitida: {sales} → {nuevo}")

            updates["sales_status"] = nuevo
            nota = f"Asesor: {sales} → {nuevo}"

            # Acciones automáticas según estado nuevo
            if nuevo == "Appointment Scheduled":
                updates["appointment_status"] = "Scheduled"
                updates["medical_status"]     = "Pending Evaluation"
                if data.doctor_id:
                    updates["doctor_id"] = data.doctor_id
                if data.treatment_date:
                    updates["treatment_date"] = data.treatment_date
                nota = "Cita de consulta agendada (pendiente confirmación)"

            elif nuevo == "Treatment Confirmed":
                # Asesor confirma que el paciente acepta la propuesta
                updates["appointment_status"] = "Confirmed"
                nota = "Paciente confirma aceptación de tratamiento"

            elif nuevo == "scheduled treatment":
                # Asesor agenda la fecha de tratamiento
                if not data.treatment_date:
                    raise HTTPException(400, "Se requiere fecha de tratamiento")
                updates["treatment_date"]     = data.treatment_date
                updates["medical_status"]     = "Treatment Scheduled"
                updates["appointment_status"] = "Confirmed"
                nota = f"Tratamiento agendado: {data.treatment_date}"

            elif nuevo == "canceled treatment":
                updates["appointment_status"] = "Canceled"
                nota = "Cancelación registrada por asesor"

            elif nuevo == "Lost":
                updates["appointment_status"] = None
                updates["medical_status"]     = None
                if data.rejection_reason:
                    updates["rejection_reason"] = data.rejection_reason
                nota = f"Lead perdido: {data.rejection_reason or 'sin razón'}"

            elif nuevo == "Follow Up":
                # Desde canceled treatment → seguimiento
                nota = "Seguimiento iniciado desde cancelación"

        else:
            raise HTTPException(400, "El asesor debe enviar sales_status o appointment_status")

    # ─────────────────────────────────────────
    #  DOCTOR
    # ─────────────────────────────────────────
    elif rol == "doctor":

        # ── In Treatment: gestión de sesiones ──
        if med == "In Treatment" and data.mark_treatment_completed is not None:

            if data.mark_treatment_completed:
                # Tratamiento completado → Won
                updates["medical_status"]     = "Treatment Completed"
                updates["sales_status"]       = "Won"
                updates["appointment_status"] = None
                updates["treatment_completed"] = True
                nota = "Tratamiento completado (Won)"

            else:
                if data.quit_reason:
                    # Paciente abandona
                    motivo = data.quit_reason
                    updates["medical_status"]     = None
                    updates["sales_status"]       = "Lost"
                    updates["appointment_status"] = None
                    updates["quit_reason"]        = motivo
                    nota = f"Paciente abandonó: {motivo}"

                elif data.next_treatment_date:
                    # Siguiente sesión
                    updates["next_treatment_date"] = data.next_treatment_date
                    nota = f"Siguiente sesión: {data.next_treatment_date}"

                else:
                    raise HTTPException(400, "Indica fecha de próxima sesión o motivo de abandono")

        # ── No Show en tratamiento → canceled treatment ──
        elif data.appointment_status == "No Show" and med in ["In Treatment","Treatment Scheduled"]:
            updates["appointment_status"] = "No Show"
            updates["sales_status"]       = "canceled treatment"
            updates["medical_status"]     = None
            nota = "No Show registrado → devuelto al asesor"

        # ── Cambio de medical_status ──
        elif data.medical_status:
            nuevo_med = data.medical_status

            # Validaciones de flujo médico
            flujo_medico = {
                "Pending Evaluation":   ["Consultation Completed", "Candidate Rejected"],
                "Consultation Completed": ["Candidate Approved", "Candidate Rejected"],
                "Candidate Approved":   ["Treatment Proposal Sent", "Candidate Rejected"],
                "Treatment Scheduled":  ["In Treatment", "Candidate Rejected"],
                "In Treatment":         [],  # se gestiona arriba con mark_treatment_completed
            }
            permitidos = flujo_medico.get(med, list(MedicalStatus.__args__))
            if nuevo_med not in permitidos and med != "":
                # Si no está en el flujo esperado, soporte puede sobreescribir; doctor solo el flujo
                raise HTTPException(400, f"Transición médica no permitida: {med} → {nuevo_med}")

            updates["medical_status"] = nuevo_med
            nota = f"Doctor: {med} → {nuevo_med}"

            if nuevo_med == "Candidate Rejected":
                if not data.rejection_reason:
                    raise HTTPException(400, "Se requiere razón de rechazo")
                updates["rejection_reason"] = data.rejection_reason
                updates["sales_status"]     = "Lost"
                updates["appointment_status"] = None
                nota = f"Candidato rechazado: {data.rejection_reason}"

            elif nuevo_med == "Treatment Proposal Sent":
                # Lead vuelve al asesor para seguimiento de propuesta
                updates["sales_status"]       = "Treatment Follow-Up"
                updates["appointment_status"] = "Sent"
                nota = "Propuesta enviada → lead devuelto al asesor (Treatment Follow-Up)"

            elif nuevo_med == "In Treatment":
                updates["appointment_status"] = "Attended"
                nota = "Paciente en tratamiento activo"

            elif nuevo_med == "Consultation Completed":
                updates["appointment_status"] = "Attended"
                nota = "Consulta completada"

        # ── Cambio de appointment_status por doctor ──
        elif data.appointment_status:
            nuevo_appt = data.appointment_status
            updates["appointment_status"] = nuevo_appt

            if nuevo_appt == "Canceled":
                if med in ["Pending Evaluation","Consultation Completed","Treatment Scheduled"]:
                    updates["sales_status"]   = "canceled treatment"
                    updates["medical_status"] = None
                nota = "Cita cancelada por doctor → devuelto al asesor"

            elif nuevo_appt == "No Show":
                updates["sales_status"]   = "canceled treatment"
                updates["medical_status"] = None
                nota = "No Show → devuelto al asesor"

            elif nuevo_appt == "Rescheduled":
                nota = "Cita reagendada por doctor"

        # ── Lost directo desde médico ──
        elif data.rejection_reason and data.medical_status is None:
            updates["medical_status"]     = "Candidate Rejected"
            updates["rejection_reason"]   = data.rejection_reason
            updates["sales_status"]       = "Lost"
            updates["appointment_status"] = None
            nota = f"Perdido por médico: {data.rejection_reason}"

        else:
            if not data.comentario:
                raise HTTPException(400, "No hay cambios válidos para el doctor")

    # ─────────────────────────────────────────
    #  SOPORTE — Control total
    # ─────────────────────────────────────────
    elif rol == "soporte":
        if data.sales_status:        updates["sales_status"]        = data.sales_status
        if data.appointment_status:  updates["appointment_status"]  = data.appointment_status
        if data.medical_status:      updates["medical_status"]      = data.medical_status
        if data.doctor_id is not None: updates["doctor_id"]         = data.doctor_id
        if data.treatment_date:      updates["treatment_date"]      = data.treatment_date
        if data.rejection_reason:    updates["rejection_reason"]    = data.rejection_reason
        if data.next_treatment_date: updates["next_treatment_date"] = data.next_treatment_date
        if data.quit_reason:         updates["quit_reason"]         = data.quit_reason
        if data.mark_treatment_completed is not None:
            updates["treatment_completed"] = data.mark_treatment_completed
        nota = "Actualización manual por soporte"

    else:
        raise HTTPException(403, "Rol no autorizado")

    # ─────────────────────────────────────────
    #  Ejecutar UPDATE
    # ─────────────────────────────────────────
    if not updates and not data.comentario:
        raise HTTPException(400, "No hay cambios para aplicar")

    updates["fecha_actualizacion"] = "now"
    set_parts, values = [], []
    for k, v in updates.items():
        if v == "now":
            set_parts.append(f"{k}=CURRENT_TIMESTAMP")
        else:
            set_parts.append(f"{k}=%s")
            values.append(v)

    values.append(data.lead_id)
    cur.execute(
        f"UPDATE leads SET {', '.join(set_parts)} WHERE id=%s RETURNING *",
        values
    )
    updated = cur.fetchone()

    # Historial
    log(nota)

    # Comentario
    if data.comentario:
        ts  = now.strftime("[%Y-%m-%d %H:%M]")
        tag = f"[{rol.upper()}]"
        nuevo_comentario = f"{ts} {tag} {data.comentario}"
        prev = lead.get("comentarios") or ""
        full = (prev + "\n" + nuevo_comentario).strip()
        cur.execute("UPDATE leads SET comentarios=%s WHERE id=%s", (full, data.lead_id))

    conn.commit(); cur.close(); conn.close()

    return {
        "id":                 updated["id"],
        "sales_status":       updated["sales_status"],
        "appointment_status": updated["appointment_status"],
        "medical_status":     updated["medical_status"],
        "message":            nota
    }

# ══════════════════════════════════════════════════════════════════
#  CREAR LEAD
# ══════════════════════════════════════════════════════════════════
@app.post("/leads")
def crear_lead(data: LeadCreate):
    conn = get_db(); cur = conn.cursor()
    asesor_id = data.asesor_id
    if not asesor_id:
        cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        if row: asesor_id = row[0]
    cur.execute(
        "INSERT INTO leads (nombre, telefono, email, categoria, canal, sales_status, asesor_id, doctor_id, creado_por) "
        "VALUES (%s,%s,%s,%s,%s,'New Lead',%s,%s,%s) RETURNING id",
        (data.nombre, data.telefono, data.email, data.categoria, data.canal, asesor_id, data.doctor_id, data.creado_por)
    )
    lead_id = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return {"id": lead_id, "message": "Lead creado"}

# ══════════════════════════════════════════════════════════════════
#  HISTORIAL
# ══════════════════════════════════════════════════════════════════
@app.get("/leads/{lead_id}/historial")
def get_historial(lead_id: int):
    conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT h.*, u.nombre FROM historial_estados h "
        "LEFT JOIN usuarios u ON h.cambiado_por = u.id "
        "WHERE h.lead_id=%s ORDER BY h.fecha DESC",
        (lead_id,)
    )
    hist = cur.fetchall(); cur.close(); conn.close()
    return {"historial": hist}

# ══════════════════════════════════════════════════════════════════
#  GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════
@app.post("/google/lead")
def recibir_lead_google(lead: LeadGoogle):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone(); asesor_id = row[0] if row else None
    cur.execute(
        "INSERT INTO leads (nombre, telefono, email, categoria, canal, sales_status, asesor_id, creado_por) "
        "VALUES (%s,%s,%s,%s,%s,'New Lead',%s,%s) RETURNING id",
        (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal, asesor_id, lead.source)
    )
    result = cur.fetchone(); conn.commit(); cur.close(); conn.close()
    return {"id": result[0], "message": "Lead creado desde Google Sheets"}

# ══════════════════════════════════════════════════════════════════
#  HEALTH
# ══════════════════════════════════════════════════════════════════
@app.get("/health")
def health():
    try:
        conn = get_db(); conn.close(); return {"status": "ok"}
    except:
        return {"status": "error"}