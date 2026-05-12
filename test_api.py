from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional, List
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

@app.middleware("http")
async def add_ngrok_header(request, call_next):
    response = await call_next(request)
    response.headers["ngrok-skip-browser-warning"] = "1"
    return response

# ============================================
# MODELOS
# ============================================
class LeadGoogle(BaseModel):
    nombre: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    pipeline: Optional[str] = "Spanish-Local"
    categoria: Optional[str] = ""
    canal: Optional[str] = "Website"
    source: Optional[str] = "google_sheets"

class UsuarioCreate(BaseModel):
    nombre: str
    email: str
    password: str
    rol: str
    telefono: Optional[str] = ""
    idiomas: Optional[str] = "spanish,espanol"

class UsuarioLogin(BaseModel):
    email: str
    password: str

class UpdateVenta(BaseModel):
    lead_id: int
    status_venta: str
    usuario_id: int
    comentario: Optional[str] = ""
    lost_reason: Optional[str] = None

class UpdateCita(BaseModel):
    lead_id: int
    status_cita: str
    usuario_id: int
    comentario: Optional[str] = ""

class UpdateMedico(BaseModel):
    lead_id: int
    status_medico: str
    usuario_id: int
    comentario: Optional[str] = ""
    doctor_id: Optional[int] = None

class CambioFase(BaseModel):
    lead_id: int
    fase: str  # 'asesor' o 'medico'
    usuario_id: int
    comentario: Optional[str] = ""
    doctor_id: Optional[int] = None

# ============================================
# BASE DE DATOS
# ============================================
def get_db():
    return psycopg2.connect(
        host="localhost", port=5432, database="stemwell",
        user="crm_user", password="crm2024"
    )

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ============================================
# LOGIN UNIFICADO
# ============================================
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

# ============================================
# USUARIOS
# ============================================
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

# ============================================
# FORMATO DE LEAD
# ============================================
def format_lead(l):
    return {
        "id": l["id"], "nombre": l["nombre"], "telefono": l["telefono"],
        "email": l["email"], "genero": l.get("genero", ""),
        "categoria": l.get("categoria", ""), "canal": l.get("canal", ""),
        "status_venta": l.get("status_venta", "New Lead"),
        "status_cita": l.get("status_cita", ""),
        "status_medico": l.get("status_medico", ""),
        "lost_reason": l.get("lost_reason", ""),
        "fase_actual": l.get("fase_actual", "asesor"),
        "asesor_id": l["asesor_id"], "doctor_id": l["doctor_id"],
        "comentarios": l.get("comentarios", ""),
        "fecha_creacion": str(l["fecha_creacion"]) if l["fecha_creacion"] else None,
        "doctor_nombre": l.get("doctor_nombre", "")
    }

# ============================================
# LEADS POR FASE (OPCIÓN A)
# ============================================
@app.get("/leads/asesor/{usuario_id}")
def leads_asesor(usuario_id: int, status_venta: Optional[str] = None):
    """Leads que el asesor debe trabajar (fase_actual = 'asesor')"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT l.*, u.nombre as doctor_nombre 
        FROM leads l 
        LEFT JOIN usuarios u ON l.doctor_id = u.id 
        WHERE l.asesor_id = %s AND l.fase_actual = 'asesor'
    """
    params = [usuario_id]
    
    if status_venta:
        query += " AND l.status_venta = %s"
        params.append(status_venta)
    
    query += " ORDER BY l.fecha_creacion DESC"
    
    cur.execute(query, params)
    leads = cur.fetchall()
    cur.close()
    conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

@app.get("/leads/medico/{usuario_id}")
def leads_medico(usuario_id: int, status_medico: Optional[str] = None):
    """Leads que el médico debe atender (fase_actual = 'medico')"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = """
        SELECT l.*, u.nombre as doctor_nombre 
        FROM leads l 
        LEFT JOIN usuarios u ON l.doctor_id = u.id 
        WHERE l.doctor_id = %s AND l.fase_actual = 'medico'
    """
    params = [usuario_id]
    
    if status_medico:
        query += " AND l.status_medico = %s"
        params.append(status_medico)
    
    query += " ORDER BY l.fecha_creacion DESC"
    
    cur.execute(query, params)
    leads = cur.fetchall()
    cur.close()
    conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

# ============================================
# CAMBIAR FASE (ASESOR ↔ MÉDICO)
# ============================================
@app.put("/leads/fase")
def cambiar_fase(data: CambioFase):
    """Mueve el lead entre asesor y médico"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM leads WHERE id = %s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    
    fase_anterior = lead["fase_actual"]
    
    updates = {"fase_actual": data.fase}
    if data.fase == "medico" and data.doctor_id:
        updates["doctor_id"] = data.doctor_id
        updates["status_medico"] = "Pending Evaluation"
    elif data.fase == "asesor":
        updates["status_venta"] = "Treatment Follow-Up"
    
    set_parts = []
    values = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        values.append(v)
    
    values.append(data.lead_id)
    cur.execute(f"UPDATE leads SET {', '.join(set_parts)}, fecha_actualizacion = NOW() WHERE id = %s RETURNING *", values)
    updated = cur.fetchone()
    
    # Historial
    cur.execute("INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) VALUES (%s,%s,%s,%s,%s)",
        (data.lead_id, f"Fase: {fase_anterior}", f"Fase: {data.fase}", data.usuario_id, data.comentario))
    
    # Notificación
    cur.execute("INSERT INTO notificaciones (lead_id, lead_nombre, usuario_nombre, tipo, mensaje) VALUES (%s,%s,(SELECT nombre FROM usuarios WHERE id=%s),'cambio_fase',%s)",
        (data.lead_id, lead["nombre"], data.usuario_id, f"Lead movido a fase: {data.fase}"))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": f"Lead movido a fase {data.fase}", "lead": format_lead(updated)}

# ============================================
# ACTUALIZAR STATUS_VENTA (ASESOR)
# ============================================
STATUS_VENTA_VALIDOS = [
    "New Lead", "First Contact", "No Answer", "Follow Up",
    "Interested", "Appointment Scheduled", "Treatment Follow-Up",
    "Treatment Confirmed", "Won", "Lost"
]

LOST_REASONS = ["No interés", "Dinero", "No apto", "No respondió", "Eligió otra clínica"]

@app.put("/leads/status-venta")
def actualizar_status_venta(data: UpdateVenta):
    if data.status_venta not in STATUS_VENTA_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Válidos: {STATUS_VENTA_VALIDOS}")
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM leads WHERE id = %s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    
    estado_anterior = lead["status_venta"]
    updates = {"status_venta": data.status_venta}
    
    if data.status_venta == "Lost" and data.lost_reason:
        updates["lost_reason"] = data.lost_reason
    if data.status_venta == "Appointment Scheduled":
        updates["status_cita"] = "Scheduled"
    
    set_parts = []
    values = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        values.append(v)
    
    values.append(data.lead_id)
    cur.execute(f"UPDATE leads SET {', '.join(set_parts)}, fecha_actualizacion = NOW() WHERE id = %s RETURNING *", values)
    updated = cur.fetchone()
    
    cur.execute("INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) VALUES (%s,%s,%s,%s,%s)",
        (data.lead_id, estado_anterior, data.status_venta, data.usuario_id, data.comentario))
    
    if data.comentario:
        ahora = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        nuevo = f"{ahora} {data.comentario}"
        comentarios = (lead["comentarios"] + "\n" + nuevo) if lead["comentarios"] else nuevo
        cur.execute("UPDATE leads SET comentarios = %s WHERE id = %s", (comentarios, data.lead_id))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Status de venta actualizado", "lead": format_lead(updated)}

# ============================================
# ACTUALIZAR STATUS_CITA
# ============================================
STATUS_CITA_VALIDOS = ["Scheduled", "Confirmed", "Rescheduled", "Cancelled", "Attended", "No Show"]

@app.put("/leads/status-cita")
def actualizar_status_cita(data: UpdateCita):
    if data.status_cita not in STATUS_CITA_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Válidos: {STATUS_CITA_VALIDOS}")
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM leads WHERE id = %s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    
    cur.execute("UPDATE leads SET status_cita = %s, fecha_actualizacion = NOW() WHERE id = %s RETURNING *",
        (data.status_cita, data.lead_id))
    updated = cur.fetchone()
    
    cur.execute("INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) VALUES (%s,%s,%s,%s,%s)",
        (data.lead_id, lead["status_cita"] or "Sin cita", data.status_cita, data.usuario_id, data.comentario))
    
    if data.comentario:
        ahora = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        nuevo = f"{ahora} {data.comentario}"
        comentarios = (lead["comentarios"] + "\n" + nuevo) if lead["comentarios"] else nuevo
        cur.execute("UPDATE leads SET comentarios = %s WHERE id = %s", (comentarios, data.lead_id))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Status de cita actualizado", "lead": format_lead(updated)}

# ============================================
# ACTUALIZAR STATUS_MEDICO (DOCTOR)
# ============================================
STATUS_MEDICO_VALIDOS = [
    "Pending Evaluation", "Consultation Completed", "Candidate Approved",
    "Candidate Rejected", "Treatment Proposal Sent", "Treatment Scheduled",
    "In Treatment", "Treatment Rescheduled", "Treatment Completed"
]

@app.put("/leads/status-medico")
def actualizar_status_medico(data: UpdateMedico):
    if data.status_medico not in STATUS_MEDICO_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Válidos: {STATUS_MEDICO_VALIDOS}")
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM leads WHERE id = %s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    
    cur.execute("UPDATE leads SET status_medico = %s, fecha_actualizacion = NOW() WHERE id = %s RETURNING *",
        (data.status_medico, data.lead_id))
    updated = cur.fetchone()
    
    cur.execute("INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) VALUES (%s,%s,%s,%s,%s)",
        (data.lead_id, lead["status_medico"] or "Sin estado médico", data.status_medico, data.usuario_id, data.comentario))
    
    if data.comentario:
        ahora = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        nuevo = f"{ahora} {data.comentario}"
        comentarios = (lead["comentarios"] + "\n" + nuevo) if lead["comentarios"] else nuevo
        cur.execute("UPDATE leads SET comentarios = %s WHERE id = %s", (comentarios, data.lead_id))
    
    # Notificar si el médico rechaza o completa
    if data.status_medico in ["Candidate Rejected", "Treatment Completed"]:
        cur.execute("INSERT INTO notificaciones (lead_id, lead_nombre, usuario_nombre, tipo, mensaje) VALUES (%s,%s,(SELECT nombre FROM usuarios WHERE id=%s),'update_medico',%s)",
            (data.lead_id, lead["nombre"], data.usuario_id, f"Médico actualizó a: {data.status_medico}"))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Status médico actualizado", "lead": format_lead(updated)}

# ============================================
# GOOGLE SHEETS
# ============================================
@app.post("/google/lead")
def recibir_lead_google(lead: LeadGoogle):
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id, nombre FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    asesor = cur.fetchone()
    
    asesor_id = asesor[0] if asesor else None
    asesor_nombre = asesor[1] if asesor else "Sin asignar"
    
    cur.execute("""
        INSERT INTO leads (nombre, telefono, email, categoria, canal, status_venta, asesor_id, creado_por, fase_actual)
        VALUES (%s, %s, %s, %s, %s, 'New Lead', %s, %s, 'asesor')
        RETURNING id, fecha_creacion
    """, (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal, asesor_id, lead.source))
    
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return {"id": result[0], "message": f"Lead asignado a {asesor_nombre}", "asesor": asesor_nombre}

# ============================================
# HISTORIAL
# ============================================
@app.get("/leads/{lead_id}/historial")
def get_historial(lead_id: int):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT h.*, u.nombre FROM historial_estados h LEFT JOIN usuarios u ON h.cambiado_por = u.id WHERE h.lead_id = %s ORDER BY h.fecha DESC", (lead_id,))
    historial = cur.fetchall()
    cur.close()
    conn.close()
    return {"historial": historial}

# ============================================
# LEADS CANCELADOS (CITA)
# ============================================
@app.get("/leads/cancelados/{asesor_id}")
def leads_cancelados(asesor_id: int):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT l.*, u.nombre as doctor_nombre FROM leads l LEFT JOIN usuarios u ON l.doctor_id = u.id WHERE l.asesor_id = %s AND l.status_cita IN ('Cancelled', 'No Show') ORDER BY l.fecha_actualizacion DESC", (asesor_id,))
    leads = cur.fetchall()
    cur.close()
    conn.close()
    return {"leads": [format_lead(l) for l in leads], "total": len(leads)}

# ============================================
# NOTIFICACIONES
# ============================================
@app.get("/notificaciones")
def get_notificaciones():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM notificaciones ORDER BY fecha DESC LIMIT 50")
    notis = cur.fetchall()
    cur.close()
    conn.close()
    return {"notificaciones": notis}

# ============================================
# ROOT & HEALTH
# ============================================
@app.get("/")
def root():
    return {"app": "CRM Stemwell", "version": "4.0.0"}

@app.get("/health")
def health():
    try:
        conn = get_db()
        conn.close()
        return {"status": "healthy"}
    except:
        return {"status": "error"}