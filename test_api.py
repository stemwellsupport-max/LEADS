from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime
import hashlib

app = FastAPI(title="CRM Stemwell API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS DE ESTADOS (LÓGICA DE NEGOCIO) ---
SalesStatus = Literal[
    "New Lead", "First Contact", "No Answer", "Follow Up", "Interested",
    "Appointment Scheduled", "Treatment Follow-Up", "scheduled treatment",
    "canceled treatment", "Won", "Lost"
]

AppointmentStatus = Literal[
    "Scheduled", "Confirmed", "Rescheduled", "No Show", "Completed"
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

# --- MODELOS PYDANTIC ---
class LeadCreate(BaseModel):
    nombre: str
    telefono: str
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = ""
    creado_por: Optional[str] = "api"

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
    # Estados que se pueden enviar
    sales_status: Optional[SalesStatus] = None
    appointment_status: Optional[AppointmentStatus] = None
    medical_status: Optional[MedicalStatus] = None
    # Datos adicionales requeridos por la lógica de negocio
    doctor_id: Optional[int] = None
    treatment_date: Optional[str] = None  # Fecha para agendar tratamiento
    rejection_reason: Optional[RejectionReason] = None

# --- BASE DE DATOS ---
def get_db():
    return psycopg2.connect(
        host="localhost", port=5432, database="stemwell",
        user="crm_user", password="crm2024"
    )

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# --- LOGIN ---
@app.post("/login")
def login(data: UsuarioLogin):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    hashed = hash_password(data.password)
    cur.execute("SELECT * FROM usuarios WHERE email = %s AND password = %s AND activo = true", (data.email, hashed))
    usuario = cur.fetchone()
    cur.close()
    conn.close()
    if not usuario:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")
    return {"id": usuario["id"], "nombre": usuario["nombre"], "email": usuario["email"], "rol": usuario["rol"]}

# --- USUARIOS ---
@app.post("/usuarios")
def crear_usuario(data: UsuarioCreate):
    conn = get_db()
    cur = conn.cursor()
    hashed = hash_password(data.password)
    cur.execute("INSERT INTO usuarios (nombre, email, password, rol, telefono, idiomas) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
        (data.nombre, data.email, hashed, data.rol, data.telefono, data.idiomas))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {"id": result[0]} if result else {"message": "Ya existe"}

@app.get("/usuarios")
def listar_usuarios(rol: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, email, rol, telefono FROM usuarios WHERE activo=true" + (" AND rol=%s" if rol else ""), (rol,) if rol else ())
    usuarios = cur.fetchall()
    cur.close()
    conn.close()
    return {"usuarios": usuarios}

@app.get("/doctores")
def listar_doctores():
    return listar_usuarios(rol="doctor")

# --- LEADS POR USUARIO (CORREGIDO) ---
def format_lead(l):
    return {
        "id": l["id"], "nombre": l["nombre"], "telefono": l["telefono"],
        "email": l["email"], "categoria": l["categoria"],
        "canal": l["canal"],
        "sales_status": l["sales_status"],
        "appointment_status": l.get("appointment_status", ""),
        "medical_status": l.get("medical_status", ""),
        "asesor_id": l["asesor_id"], "doctor_id": l.get("doctor_id"),
        "doctor_nombre": l.get("doctor_nombre", ""),
        "comentarios": l["comentarios"],
        "rejection_reason": l.get("rejection_reason", ""),
        "fecha_creacion": str(l["fecha_creacion"]) if l["fecha_creacion"] else None,
        "treatment_date": str(l["treatment_date"]) if l.get("treatment_date") else None,
    }

@app.get("/leads/usuario/{usuario_id}")
def leads_por_usuario(usuario_id: int, estado: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT rol FROM usuarios WHERE id = %s", (usuario_id,))
    user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    if user["rol"] == "asesor":
        # Para asesores, filtrar por sales_status
        query = """
            SELECT l.*, u.nombre as doctor_nombre 
            FROM leads l 
            LEFT JOIN usuarios u ON l.doctor_id = u.id 
            WHERE l.asesor_id = %s
        """
        if estado:
            query += " AND l.sales_status = %s"
    elif user["rol"] == "doctor":
        # Para doctores, filtrar por medical_status o appointment_status
        query = """
            SELECT l.*, u.nombre as doctor_nombre 
            FROM leads l 
            LEFT JOIN usuarios u ON l.doctor_id = u.id 
            WHERE l.doctor_id = %s
        """
        if estado:
            query += " AND (l.medical_status = %s OR l.appointment_status = %s)"
    else:
        query = "SELECT l.*, u.nombre as doctor_nombre FROM leads l LEFT JOIN usuarios u ON l.doctor_id = u.id WHERE 1=1"
        if estado:
            query += " AND (l.sales_status = %s OR l.medical_status = %s)"
    
    params = [usuario_id]
    if estado:
        params.append(estado)
        if user["rol"] != "asesor":
            params.append(estado)  # Para el OR en roles no asesor
    
    query += " ORDER BY l.fecha_creacion DESC"
    
    cur.execute(query, params)
    leads = cur.fetchall()
    cur.close()
    conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

# --- CAMBIAR ESTADO (LÓGICA PRINCIPAL CORREGIDA) ---
@app.put("/leads/estado")
def cambiar_estado(data: UpdateStatus):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Obtener lead y usuario
    cur.execute("SELECT * FROM leads WHERE id = %s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    
    cur.execute("SELECT * FROM usuarios WHERE id = %s", (data.usuario_id,))
    usuario = cur.fetchone()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    rol = usuario["rol"]
    nuevo_comentario = data.comentario
    estado_anterior_sales = lead["sales_status"]
    estado_anterior_medico = lead["medical_status"]
    estado_anterior_cita = lead["appointment_status"]
    
    updates = {}
    historial_extra = ""
    
    # 2. LÓGICA DE TRANSICIÓN POR ROL
    if rol == "asesor":
        # Validar que el asesor solo mande sales_status
        if not data.sales_status:
            raise HTTPException(status_code=400, detail="Asesor debe especificar sales_status")
        
        nuevo_sales = data.sales_status
        
        # Validar transiciones permitidas
        transiciones_asesor = {
            "New Lead": ["First Contact", "No Answer", "Follow Up", "Interested", "Appointment Scheduled"],
            "First Contact": ["Follow Up", "Interested", "Appointment Scheduled", "No Answer"],
            "No Answer": ["Follow Up", "First Contact"],
            "Follow Up": ["Interested", "Appointment Scheduled", "Lost"],
            "Interested": ["Appointment Scheduled", "Follow Up", "Lost"],
            "Appointment Scheduled": ["Won", "Lost", "canceled treatment"],
            "Treatment Follow-Up": ["scheduled treatment", "Lost"],
            "scheduled treatment": ["Won", "Lost", "canceled treatment"],
        }
        
        if estado_anterior_sales not in transiciones_asesor or nuevo_sales not in transiciones_asesor[estado_anterior_sales]:
            raise HTTPException(status_code=400, detail=f"Transición de {estado_anterior_sales} a {nuevo_sales} no permitida para asesor")
        
        updates["sales_status"] = nuevo_sales
        historial_extra = f"[SALES] {estado_anterior_sales} → {nuevo_sales}"
        
        # Acciones automáticas
        if nuevo_sales == "Appointment Scheduled":
            if not data.doctor_id:
                raise HTTPException(status_code=400, detail="Se requiere doctor_id para agendar cita")
            updates["doctor_id"] = data.doctor_id
            updates["appointment_status"] = "Scheduled"
            updates["medical_status"] = "Pending Evaluation"
            historial_extra += " | Cita agendada y asignada a doctor"
            
        elif nuevo_sales == "scheduled treatment":
            if not data.treatment_date:
                raise HTTPException(status_code=400, detail="Se requiere fecha de tratamiento para agendar")
            updates["treatment_date"] = data.treatment_date
            updates["appointment_status"] = "Scheduled"
            updates["medical_status"] = "Treatment Scheduled"
            historial_extra += f" | Tratamiento agendado para {data.treatment_date}"
            
        elif nuevo_sales == "Lost":
            updates["appointment_status"] = None
            updates["medical_status"] = None
            
    elif rol == "doctor":
        # El doctor puede cambiar appointment_status y medical_status
        if data.appointment_status:
            nuevo_appt = data.appointment_status
            if data.appointment_status == "No Show":
                if lead["medical_status"] in ["In Treatment", "Treatment Scheduled"]:
                    # No Show en tratamiento devuelve el lead al asesor
                    updates["sales_status"] = "canceled treatment"
                    updates["appointment_status"] = "No Show"
                    historial_extra += f"[APPOINTMENT] No Show en tratamiento. Lead devuelto a asesor."
                else:
                    updates["appointment_status"] = "No Show"
                    historial_extra += f"[APPOINTMENT] {estado_anterior_cita} → No Show"
            else:
                updates["appointment_status"] = nuevo_appt
                historial_extra += f"[APPOINTMENT] {estado_anterior_cita} → {nuevo_appt}"
        
        if data.medical_status:
            nuevo_med = data.medical_status
            
            if nuevo_med == "Candidate Rejected":
                if not data.rejection_reason:
                    raise HTTPException(status_code=400, detail="Se requiere razón de rechazo")
                updates["rejection_reason"] = data.rejection_reason
                updates["sales_status"] = "Lost"  # Devuelve a asesor como perdido
                historial_extra += f"[MEDICAL] Candidate Rejected: {data.rejection_reason}. Lead movido a Lost."
                
            elif nuevo_med == "Treatment Proposal Sent":
                # Devolver al asesor original para seguimiento
                updates["sales_status"] = "Treatment Follow-Up"
                historial_extra += "[MEDICAL] Propuesta enviada. Lead devuelto a asesor para seguimiento."
                
            elif nuevo_med == "Treatment Completed":
                updates["sales_status"] = "Won"
                historial_extra += "[MEDICAL] Tratamiento completado. Lead ganado."
                
            updates["medical_status"] = nuevo_med
            if not historial_extra:
                historial_extra += f"[MEDICAL] {estado_anterior_medico} → {nuevo_med}"
    
    else:
        raise HTTPException(status_code=403, detail="Rol no autorizado para cambiar estados")
    
    # 3. Construir y ejecutar UPDATE
    updates["fecha_actualizacion"] = "now"
    set_parts = []
    values = []
    for k, v in updates.items():
        if v == "now":
            set_parts.append(f"{k} = CURRENT_TIMESTAMP")
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)
    
    values.append(data.lead_id)
    cur.execute(f"UPDATE leads SET {', '.join(set_parts)} WHERE id = %s RETURNING *", values)
    updated = cur.fetchone()
    
    # 4. Historial
    cur.execute("INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) VALUES (%s,%s,%s,%s,%s)",
        (data.lead_id, f"S:{estado_anterior_sales}|M:{estado_anterior_medico}|A:{estado_anterior_cita}", 
         f"S:{updated['sales_status']}|M:{updated['medical_status']}|A:{updated['appointment_status']}", 
         data.usuario_id, historial_extra))
    
    # 5. Comentario
    if nuevo_comentario:
        ahora = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        tag = "[SALES]" if rol == "asesor" else "[MEDICAL]"
        nuevo = f"{ahora} {tag} {nuevo_comentario}"
        comentarios = (lead["comentarios"] + "\n" + nuevo) if lead["comentarios"] else nuevo
        cur.execute("UPDATE leads SET comentarios = %s WHERE id = %s", (comentarios, data.lead_id))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return {
        "id": updated["id"], 
        "sales_status": updated["sales_status"],
        "appointment_status": updated["appointment_status"],
        "medical_status": updated["medical_status"],
        "message": f"Estado actualizado. {historial_extra}"
    }

# --- HISTORIAL, CANCELADOS, GOOGLE SHEETS, NOTIFICACIONES (Mantener igual, ajustar queries si es necesario) ---
# ... (El resto del código se mantiene similar, solo asegurando que las queries usen sales_status si es necesario)

@app.get("/leads/{lead_id}/historial")
def get_historial(lead_id: int):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT h.*, u.nombre FROM historial_estados h LEFT JOIN usuarios u ON h.cambiado_por = u.id WHERE h.lead_id = %s ORDER BY h.fecha DESC", (lead_id,))
    historial = cur.fetchall()
    cur.close()
    conn.close()
    return {"historial": historial}

@app.get("/leads/cancelados/{asesor_id}")
def leads_cancelados(asesor_id: int):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE asesor_id = %s AND (sales_status = 'canceled treatment' OR sales_status = 'Lost') ORDER BY fecha_actualizacion DESC", (asesor_id,))
    leads = cur.fetchall()
    cur.close()
    conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

@app.post("/google/lead")
def recibir_lead_google(lead: LeadGoogle):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    asesor = cur.fetchone()
    asesor_id = asesor[0] if asesor else None
    
    cur.execute("""
        INSERT INTO leads (nombre, telefono, email, categoria, canal, sales_status, asesor_id, creado_por)
        VALUES (%s, %s, %s, %s, %s, 'New Lead', %s, %s) RETURNING id
    """, (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal, asesor_id, lead.source))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {"id": result[0], "message": "Lead creado"}