# app/models/schemas.py
from pydantic import BaseModel
from typing import Optional, Any

class UsuarioLogin(BaseModel):
    email: str
    password: str

class UsuarioCreate(BaseModel):
    nombre: str
    email: str
    password: str
    rol: str
    telefono: Optional[str] = ""
    idiomas: Optional[str] = "spanish"

class LeadCreate(BaseModel):
    nombre: str
    telefono: str
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = "Manual"
    genero: Optional[str] = ""
    ciudad: Optional[str] = ""
    pais: Optional[str] = ""               # ← NUEVO
    notas: Optional[str] = ""
    pipeline: Optional[str] = ""
    sales_status_inicial: Optional[str] = "New Lead"
    asesor_id: Optional[int] = None
    doctor_id: Optional[int] = None
    creado_por: Optional[str] = "soporte"

class LeadGoogle(BaseModel):
    nombre: str
    phone: str
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = "Google Sheets"
    source: Optional[str] = "google"

class UpdateStatus(BaseModel):
    lead_id: int
    usuario_id: int
    comentario: Optional[str] = ""

    # Estados
    sales_status: Optional[str] = None
    appointment_status: Optional[str] = None
    medical_status: Optional[str] = None

    # Pipeline
    pipeline: Optional[str] = None     
    pais: Optional[str] = None      # ← NUEVO

    # Asignaciones
    doctor_id: Optional[int] = None

    # Fechas
    treatment_date: Optional[str] = None
    treatment_start_date: Optional[str] = None
    treatment_end_date: Optional[str] = None
    next_treatment_date: Optional[str] = None
    last_contact_date: Optional[str] = None

    # Datos adicionales
    medilink_numero: Optional[str] = None
    rejection_reason: Optional[str] = None
    quit_reason: Optional[str] = None

    # Flags booleanos
    cita_confirmada: Optional[bool] = None
    mark_treatment_completed: Optional[bool] = None
    treatment_confirmed: Optional[bool] = None
    confirm_reschedule: Optional[bool] = None

    # Booked call desde modal principal
    booked_call_fecha: Optional[str] = None
    booked_call_tipo: Optional[str] = "Llamada"
    booked_call_notas: Optional[str] = ""

    # Control embebido
    crear_control: Optional[Any] = None

class BookedCallCreate(BaseModel):
    lead_id: int
    asesor_id: int
    fecha_llamada: str
    tipo: Optional[str] = "Llamada"
    notas: Optional[str] = ""

class BookedCallUpdate(BaseModel):
    estado: Optional[str] = None
    notas: Optional[str] = None
    fecha_llamada: Optional[str] = None
    tipo: Optional[str] = None