from pydantic import BaseModel
from typing import Optional, Literal

# ══════════════════════════════════════════════════════════════════
#  TIPOS
# ══════════════════════════════════════════════════════════════════
SalesStatus = Literal[
    "New Lead", "First Contact", "No Answer", "Follow Up", "Interested",
    "Appointment Scheduled",
    "Treatment Proposal Sent",
    "scheduled treatment",
    "canceled treatment",
    "Won", "Lost"
]
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
    sales_status: Optional[SalesStatus] = None
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

class LeadGoogle(BaseModel):
    nombre: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    categoria: Optional[str] = ""
    canal: Optional[str] = "Website"
    source: Optional[str] = "google_sheets"
    genero: Optional[str] = ""
    comentario: Optional[str] = ""
    admission_date: Optional[str] = None
    last_contact_date: Optional[str] = None
    first_contact: Optional[str] = None        # ← NOMBRE de quien contactó (TEXTO)
    sales_status: Optional[str] = None
    asesor_id: Optional[int] = None