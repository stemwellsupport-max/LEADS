from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime
import hashlib
from typing import Optional
from schemas import (
    LeadCreate, UsuarioCreate, UsuarioLogin,
    UpdateStatus, BookedCallCreate, BookedCallUpdate, LeadGoogle
)

app = FastAPI(title="Patient Tracking Sheet", version="9.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== CONNECTION POOL ==========
_pool = pool.ThreadedConnectionPool(
    minconn=2, maxconn=10,
    host="localhost", port=5432,
    database="stemwell", user="crm_user", password="crm2024"
)

def get_db():
    return _pool.getconn()

def release_db(conn):
    _pool.putconn(conn)

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

# ========== SETUP TABLAS ==========
def ensure_tables():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS booked_calls (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                asesor_id INTEGER NOT NULL REFERENCES usuarios(id),
                fecha_llamada TIMESTAMP NOT NULL,
                tipo VARCHAR(50) DEFAULT 'Llamada',
                notas TEXT DEFAULT '',
                estado VARCHAR(50) DEFAULT 'Pendiente',
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agenda_doctor (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                doctor_id INTEGER NOT NULL REFERENCES usuarios(id),
                fecha_inicio TIMESTAMP NOT NULL,
                fecha_fin TIMESTAMP NOT NULL,
                estado VARCHAR(50) DEFAULT 'Scheduled',
                tipo VARCHAR(50) DEFAULT 'Consulta',
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS controles (
                id SERIAL PRIMARY KEY,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                tipo VARCHAR(100) DEFAULT 'Control',
                descripcion TEXT DEFAULT '',
                fecha_control TIMESTAMP,
                doctor_id INTEGER REFERENCES usuarios(id),
                asesor_id INTEGER REFERENCES usuarios(id),
                estado VARCHAR(50) DEFAULT 'Agendado',
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='leads' AND column_name='treatment_confirmed') THEN
                    ALTER TABLE leads ADD COLUMN treatment_confirmed BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='leads' AND column_name='confirm_reschedule') THEN
                    ALTER TABLE leads ADD COLUMN confirm_reschedule BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        conn.commit()
        cur.close()
        print("✅ Tablas y columnas verificadas")
    except Exception as e:
        print(f"⚠️ Error: {e}")
    finally:
        release_db(conn)

ensure_tables()

# ========== AUXILIARES AGENDA ==========
def _parse_fecha(v):
    if not v: return None
    s = str(v)
    if "T" in s: return s.replace("T", " ")
    if " " in s: return s
    return s + " 00:00:00"

def sync_agenda(conn, lead_id, treatment_date, doctor_id, estado='Scheduled'):
    if not treatment_date or not doctor_id: return
    fecha = _parse_fecha(treatment_date)
    cur = conn.cursor()
    cur.execute("SELECT id FROM agenda_doctor WHERE lead_id = %s", (lead_id,))
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

def delete_from_agenda(conn, lead_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM agenda_doctor WHERE lead_id=%s", (lead_id,))
    cur.close()

def update_agenda_estado(conn, lead_id, estado):
    cur = conn.cursor()
    cur.execute("UPDATE agenda_doctor SET estado=%s, fecha_actualizacion=CURRENT_TIMESTAMP WHERE lead_id=%s",
                (estado, lead_id))
    cur.close()

def update_agenda_fecha(conn, lead_id, treatment_date, estado='Rescheduled'):
    if not treatment_date: return
    fecha = _parse_fecha(treatment_date)
    cur = conn.cursor()
    cur.execute("""UPDATE agenda_doctor
        SET fecha_inicio=%s::timestamp, fecha_fin=%s::timestamp, estado=%s,
            fecha_actualizacion=CURRENT_TIMESTAMP
        WHERE lead_id=%s""", (fecha, fecha, estado, lead_id))
    cur.close()

# ========== FORMAT LEAD ==========
def dt(v):
    if not v: return None
    s = str(v)
    return s.split(" ")[0] if " " in s else (s.split("T")[0] if "T" in s else s)

def format_lead(l):
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
        "treatment_confirmed": l.get("treatment_confirmed", False),
        "treatment_date": dt(l.get("treatment_date")),
        "treatment_start_date": dt(l.get("treatment_start_date")),
        "treatment_end_date": dt(l.get("treatment_end_date")),
        "next_treatment_date": dt(l.get("next_treatment_date")),
        "treatment_completed": l.get("treatment_completed", False),
        "fecha_creacion": dt(l.get("fecha_creacion")),
        "fecha_actualizacion": dt(l.get("fecha_actualizacion")),
        "admission_date": dt(l.get("admission_date") or l.get("fecha_creacion")),
        "last_contact_date": dt(l.get("last_contact_date") or l.get("fecha_actualizacion")),
        "semaforo": l.get("semaforo") or "",
        "pipeline": l.get("pipeline") or "",
    }

# ========== AUTH ==========
@app.post("/login")
def login(data: UsuarioLogin):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM usuarios WHERE email=%s AND password=%s AND activo=true",
                    (data.email, hash_password(data.password)))
        user = cur.fetchone()
        cur.close()
        if not user: raise HTTPException(401, "Credenciales inválidas")
        return {"id": user["id"], "nombre": user["nombre"], "email": user["email"], "rol": user["rol"]}
    finally:
        release_db(conn)

# ========== USUARIOS ==========
@app.post("/usuarios")
def crear_usuario(data: UsuarioCreate):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO usuarios (nombre,email,password,rol,telefono,idiomas) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id",
            (data.nombre, data.email, hash_password(data.password), data.rol, data.telefono, data.idiomas)
        )
        res = cur.fetchone()
        conn.commit(); cur.close()
        return {"id": res[0]} if res else {"message": "Ya existe"}
    finally:
        release_db(conn)

@app.get("/usuarios")
def listar_usuarios(rol: Optional[str] = None):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if rol:
            cur.execute("SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true AND rol=%s", (rol,))
        else:
            cur.execute("SELECT id,nombre,email,rol,telefono FROM usuarios WHERE activo=true")
        usuarios = cur.fetchall()
        cur.close()
        return {"usuarios": usuarios}
    finally:
        release_db(conn)

@app.get("/doctores")
def listar_doctores(): return listar_usuarios(rol="doctor")

@app.get("/asesores")
def listar_asesores(): return listar_usuarios(rol="asesor")

@app.put("/usuarios/{usuario_id}/password")
def cambiar_password(usuario_id: int, data: dict):
    nueva = data.get("nueva_password", "")
    if len(nueva) < 6: raise HTTPException(400, "Contraseña mínimo 6 caracteres")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE usuarios SET password=%s WHERE id=%s", (hash_password(nueva), usuario_id))
        conn.commit(); cur.close()
        return {"message": "Contraseña actualizada"}
    finally:
        release_db(conn)

# ========== TRANSFERIR LEAD ==========
@app.put("/leads/{lead_id}/transferir")
def transferir_lead(lead_id: int, data: dict):
    nuevo_asesor_id = data.get("nuevo_asesor_id")
    usuario_id = data.get("usuario_id")
    if not nuevo_asesor_id:
        raise HTTPException(400, "nuevo_asesor_id es obligatorio")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nombre, asesor_id, sales_status FROM leads WHERE id=%s", (lead_id,))
        lead = cur.fetchone()
        if not lead: raise HTTPException(404, "Lead no encontrado")
        cur.execute("SELECT id, nombre FROM usuarios WHERE id=%s AND rol='asesor' AND activo=true",
                    (nuevo_asesor_id,))
        nuevo_asesor = cur.fetchone()
        if not nuevo_asesor: raise HTTPException(400, "Asesor destino no válido")
        asesor_anterior_id = lead["asesor_id"]
        cur.execute("SELECT nombre FROM usuarios WHERE id=%s", (asesor_anterior_id,))
        row = cur.fetchone()
        asesor_anterior_nombre = row["nombre"] if row else "Desconocido"
        cur.execute("UPDATE leads SET asesor_id=%s, fecha_actualizacion=CURRENT_TIMESTAMP WHERE id=%s",
                    (nuevo_asesor_id, lead_id))
        cur.execute(
            "INSERT INTO historial_estados (lead_id, estado_anterior, estado_nuevo, cambiado_por, comentario) "
            "VALUES (%s, %s, %s, %s, %s)",
            (lead_id, f"ASESOR:{asesor_anterior_nombre}", f"ASESOR:{nuevo_asesor['nombre']}",
             usuario_id, f"Lead transferido de {asesor_anterior_nombre} a {nuevo_asesor['nombre']}")
        )
        conn.commit(); cur.close()
        return {
            "message": f"Lead transferido a {nuevo_asesor['nombre']}",
            "lead_id": lead_id,
            "nuevo_asesor_id": nuevo_asesor_id,
            "nuevo_asesor_nombre": nuevo_asesor["nombre"]
        }
    finally:
        release_db(conn)

# ========== BOOKED CALLS ==========
@app.post("/booked-calls")
def crear_booked_call(data: BookedCallCreate):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, nombre, sales_status FROM leads WHERE id=%s", (data.lead_id,))
        lead = cur.fetchone()
        if not lead: raise HTTPException(404, "Lead no encontrado")
        cur.execute("SELECT id, nombre FROM usuarios WHERE id=%s AND rol='asesor'", (data.asesor_id,))
        asesor = cur.fetchone()
        if not asesor: raise HTTPException(400, "Asesor no válido")
        cur.execute(
            "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
            "VALUES (%s,%s,%s,%s,%s,'Pendiente') RETURNING id,creado_en",
            (data.lead_id, data.asesor_id, data.fecha_llamada, data.tipo or "Llamada", data.notas or "")
        )
        result = cur.fetchone()
        cur.execute("UPDATE leads SET sales_status='Booked Calls', fecha_actualizacion=CURRENT_TIMESTAMP WHERE id=%s",
                    (data.lead_id,))
        cur.execute("INSERT INTO historial_estados (lead_id,estado_anterior,estado_nuevo,cambiado_por,comentario) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (data.lead_id, f"S:{lead['sales_status']}", "S:Booked Calls",
                     data.asesor_id, f"Llamada reservada: {data.fecha_llamada}"))
        conn.commit(); cur.close()
        return {"id": result["id"], "message": "Llamada reservada creada", "lead_nombre": lead["nombre"]}
    finally:
        release_db(conn)

@app.get("/booked-calls")
def listar_booked_calls(asesor_id: Optional[int] = None, estado: Optional[str] = None,
                        lead_id: Optional[int] = None):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        where, params = ["1=1"], []
        if asesor_id: where.append("bc.asesor_id=%s"); params.append(asesor_id)
        if estado: where.append("bc.estado=%s"); params.append(estado)
        if lead_id: where.append("bc.lead_id=%s"); params.append(lead_id)
        cur.execute(f"""
            SELECT bc.*, l.nombre AS lead_nombre, l.telefono AS lead_telefono,
                   l.email AS lead_email, l.categoria AS lead_categoria,
                   l.sales_status AS lead_sales_status, a.nombre AS asesor_nombre
            FROM booked_calls bc
            JOIN leads l ON bc.lead_id=l.id
            JOIN usuarios a ON bc.asesor_id=a.id
            WHERE {' AND '.join(where)}
            ORDER BY bc.fecha_llamada DESC
        """, params)
        calls = cur.fetchall(); cur.close()
        return {"calls": [dict(c) for c in calls], "total": len(calls)}
    finally:
        release_db(conn)

@app.put("/booked-calls/{call_id}")
def actualizar_booked_call(call_id: int, data: BookedCallUpdate):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM booked_calls WHERE id=%s", (call_id,))
        call = cur.fetchone()
        if not call: raise HTTPException(404, "Llamada no encontrada")
        updates = {}
        if data.estado: updates["estado"] = data.estado
        if data.notas is not None: updates["notas"] = data.notas
        if data.fecha_llamada: updates["fecha_llamada"] = data.fecha_llamada
        if data.tipo: updates["tipo"] = data.tipo
        if updates:
            set_parts, values = [], []
            for k, v in updates.items():
                set_parts.append(f"{k}=%s"); values.append(v)
            set_parts.append("actualizado_en=CURRENT_TIMESTAMP")
            values.append(call_id)
            cur.execute(f"UPDATE booked_calls SET {', '.join(set_parts)} WHERE id=%s RETURNING *", values)
            updated = cur.fetchone()
            if data.estado == "Realizada":
                cur.execute("UPDATE leads SET sales_status='Follow Up', fecha_actualizacion=CURRENT_TIMESTAMP WHERE id=%s",
                            (call["lead_id"],))
        else:
            updated = call
        conn.commit(); cur.close()
        return {"message": "Llamada actualizada", "call": dict(updated)}
    finally:
        release_db(conn)

@app.delete("/booked-calls/{call_id}")
def eliminar_booked_call(call_id: int):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT lead_id FROM booked_calls WHERE id=%s", (call_id,))
        call = cur.fetchone()
        if not call: raise HTTPException(404, "Llamada no encontrada")
        lead_id = call["lead_id"]
        cur.execute("DELETE FROM booked_calls WHERE id=%s", (call_id,))
        cur.execute("SELECT COUNT(*) as cnt FROM booked_calls WHERE lead_id=%s", (lead_id,))
        if cur.fetchone()["cnt"] == 0:
            cur.execute("UPDATE leads SET sales_status='First Contact', fecha_actualizacion=CURRENT_TIMESTAMP "
                        "WHERE id=%s AND sales_status='Booked Calls'", (lead_id,))
        conn.commit(); cur.close()
        return {"message": "Llamada eliminada"}
    finally:
        release_db(conn)

@app.get("/leads/{lead_id}/booked-calls")
def get_booked_calls_lead(lead_id: int):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT bc.*, a.nombre AS asesor_nombre FROM booked_calls bc
            JOIN usuarios a ON bc.asesor_id=a.id
            WHERE bc.lead_id=%s ORDER BY bc.fecha_llamada DESC
        """, (lead_id,))
        calls = cur.fetchall(); cur.close()
        return {"calls": [dict(c) for c in calls]}
    finally:
        release_db(conn)

# ========== LEADS - GET ==========
@app.get("/leads/usuario/{usuario_id}")
def leads_por_usuario(usuario_id: int, estado: Optional[str] = None):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT rol FROM usuarios WHERE id=%s", (usuario_id,))
        user = cur.fetchone()
        if not user: raise HTTPException(404, "Usuario no encontrado")
        rol = user["rol"]
        base = """SELECT l.*, d.nombre AS doctor_nombre, a.nombre AS asesor_nombre
            FROM leads l
            LEFT JOIN usuarios d ON l.doctor_id=d.id
            LEFT JOIN usuarios a ON l.asesor_id=a.id"""
        if rol == "asesor":
            where = "WHERE l.asesor_id=%s"
            params = [usuario_id]
            if estado: where += " AND l.sales_status=%s"; params.append(estado)
        elif rol == "doctor":
            where = """WHERE l.doctor_id=%s AND l.medical_status IS NOT NULL
                AND l.medical_status NOT IN ('Treatment Completed','Candidate Rejected')"""
            params = [usuario_id]
            if estado:
                where = "WHERE l.doctor_id=%s AND l.medical_status=%s"
                params = [usuario_id, estado]
        elif rol == "visitas":
            where = """WHERE l.sales_status IN (
                'Appointment Scheduled',
                'Treatment Proposal Sent',
                'scheduled treatment',
                'canceled treatment',
                'Won',
                'International line',
                'Rescheduled',
                'canceled call',
                'treatment_confirmed'
            )"""
            params = []
            if estado:
                where += " AND l.sales_status=%s"
                params.append(estado)
        else:
            where = "WHERE 1=1"
            params = []
            if estado:
                where += " AND (l.sales_status=%s OR l.medical_status=%s)"
                params = [estado, estado]
        cur.execute(base + " " + where + " ORDER BY l.fecha_actualizacion DESC", params)
        leads = cur.fetchall(); cur.close()
        return {"leads": [format_lead(l) for l in leads], "total": len(leads)}
    finally:
        release_db(conn)

# ========== LEADS - UPDATE STATUS (CON actualización de last_contact_date) ==========
@app.put("/leads/estado")
def cambiar_estado(data: UpdateStatus):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM leads WHERE id=%s", (data.lead_id,))
        lead = cur.fetchone()
        if not lead: raise HTTPException(404, "Lead no encontrado")
        cur.execute("SELECT * FROM usuarios WHERE id=%s", (data.usuario_id,))
        usuario = cur.fetchone()
        if not usuario: raise HTTPException(404, "Usuario no encontrado")

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
                (data.lead_id, f"S:{sales}|A:{appt}|M:{med}",
                 f"S:{after_s}|A:{after_a}|M:{after_m}",
                 data.usuario_id, nota or data.comentario or "")
            )

        # ========== ASESOR ==========
        if rol == "asesor":
            if data.sales_status == "Booked Calls":
                updates["sales_status"] = "Booked Calls"
                nota = "Cambio a Booked Calls"
                if data.booked_call_fecha:
                    cur.execute(
                        "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
                        "VALUES (%s,%s,%s,%s,%s,'Pendiente')",
                        (data.lead_id, data.usuario_id, data.booked_call_fecha,
                         data.booked_call_tipo or "Llamada", data.booked_call_notas or "")
                    )
                    nota = f"Llamada reservada para {data.booked_call_fecha}"
            elif data.cita_confirmada is True and sales == "Appointment Scheduled":
                if not data.doctor_id: raise HTTPException(400, "Se requiere doctor para confirmar")
                updates["cita_confirmada"] = True
                updates["appointment_status"] = "Confirmed"
                updates["doctor_id"] = data.doctor_id
                if not med: updates["medical_status"] = "Pending Evaluation"
                if data.treatment_date: updates["treatment_date"] = data.treatment_date
                nota = f"Cita confirmada → doctor id={data.doctor_id}"
                update_agenda_estado(conn, data.lead_id, 'Confirmed')
            elif data.cita_confirmada is False and sales == "Appointment Scheduled" and lead.get("cita_confirmada"):
                updates["cita_confirmada"] = False
                updates["appointment_status"] = "Scheduled"
                nota = "Cita desconfirmada por asesor"
                update_agenda_estado(conn, data.lead_id, 'Scheduled')
            elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
                updates["sales_status"] = "canceled treatment"
                updates["appointment_status"] = "Canceled"
                updates["cita_confirmada"] = False
                updates["medical_status"] = None
                nota = "Cita cancelada por asesor"
                delete_from_agenda(conn, data.lead_id)
            elif data.appointment_status == "No Show" and sales == "Appointment Scheduled":
                updates["sales_status"] = "canceled treatment"
                updates["appointment_status"] = "No Show"
                updates["cita_confirmada"] = False
                updates["medical_status"] = None
                nota = "No Show marcado por asesor"
                delete_from_agenda(conn, data.lead_id)
            elif data.appointment_status == "Rescheduled" and sales == "Appointment Scheduled":
                updates["appointment_status"] = "Rescheduled"
                if data.treatment_date: updates["treatment_date"] = data.treatment_date
                nota = "Cita reagendada por asesor"
                update_agenda_fecha(conn, data.lead_id, data.treatment_date, 'Rescheduled')
            elif data.sales_status == "scheduled treatment" and sales == "Treatment Proposal Sent":
                if not lead.get("treatment_confirmed"):
                    raise HTTPException(400, "El paciente aún no ha confirmado la propuesta de tratamiento")
                if not data.treatment_date:
                    raise HTTPException(400, "Fecha tentativa de inicio obligatoria")
                updates["sales_status"] = "scheduled treatment"
                updates["medical_status"] = "Treatment Scheduled"
                updates["appointment_status"] = "Scheduled"
                updates["cita_confirmada"] = False
                updates["treatment_date"] = data.treatment_date
                if data.doctor_id: updates["doctor_id"] = data.doctor_id
                nota = f"Inicio de tratamiento agendado: {data.treatment_date}"
                sync_agenda(conn, data.lead_id, data.treatment_date, data.doctor_id or lead.get("doctor_id"), 'Scheduled')
            elif data.cita_confirmada is True and sales == "scheduled treatment":
                updates["cita_confirmada"] = True
                updates["appointment_status"] = "Confirmed"
                nota = "Asesor confirmó asistencia del paciente al tratamiento"
                update_agenda_estado(conn, data.lead_id, 'Confirmed')
            elif data.confirm_reschedule is True and sales == "Rescheduled Treatment":
                if not data.treatment_date: raise HTTPException(400, "Se requiere nueva fecha para confirmar reagenda")
                updates["sales_status"] = "scheduled treatment"
                updates["medical_status"] = "Treatment Scheduled"
                updates["appointment_status"] = "Scheduled"
                updates["cita_confirmada"] = False
                updates["treatment_date"] = data.treatment_date
                nota = f"Reagenda de tratamiento confirmada por asesor: {data.treatment_date}"
                sync_agenda(conn, data.lead_id, data.treatment_date, lead.get("doctor_id"), 'Scheduled')
            elif data.sales_status == "Appointment Scheduled" and sales == "canceled treatment":
                if not data.medilink_numero and not lead.get("medilink_numero"):
                    raise HTTPException(400, "Número de paciente (medilink) obligatorio para agendar consulta")
                updates["sales_status"] = "Appointment Scheduled"
                updates["appointment_status"] = "Scheduled"
                updates["cita_confirmada"] = False
                if data.doctor_id: updates["doctor_id"] = data.doctor_id
                if data.treatment_date: updates["treatment_date"] = data.treatment_date
                if data.medilink_numero: updates["medilink_numero"] = data.medilink_numero
                nota = "Consulta reagendada desde cancelación"
                sync_agenda(conn, data.lead_id, data.treatment_date, data.doctor_id, 'Scheduled')
            elif data.sales_status == "Treatment Proposal Sent" and sales == "canceled treatment":
                updates["sales_status"] = "Treatment Proposal Sent"
                nota = "Tratamiento reagendado"
            elif data.sales_status == "Follow Up" and sales == "canceled treatment":
                updates["sales_status"] = "Follow Up"
                nota = "Seguimiento iniciado"
            elif sales == "Treatment Proposal Sent" and data.appointment_status in ["Canceled", "No Show"]:
                updates["sales_status"] = "canceled treatment"
                updates["appointment_status"] = data.appointment_status
                nota = f"Tratamiento {data.appointment_status}"
            elif data.sales_status:
                nuevo = data.sales_status
                trans_validas = {
                    "New Lead":      ["First Contact","No Answer","Follow Up","Interested","Appointment Scheduled","Lost","Booked Calls","At reception","International line"],
                    "First Contact": ["Follow Up","Interested","Appointment Scheduled","No Answer","Lost","Booked Calls","At reception"],
                    "No Answer":     ["Follow Up","First Contact","Lost","Booked Calls","At reception"],
                    "Follow Up":     ["Interested","Appointment Scheduled","Lost","Booked Calls","At reception"],
                    "Interested":    ["Appointment Scheduled","Follow Up","Lost","Booked Calls","At reception"],
                    "Booked Calls":  ["First Contact","Follow Up","Interested","Appointment Scheduled","Lost","No Answer","At reception"],
                    "At reception":  ["Appointment Scheduled","Interested","Follow Up","Lost","Booked Calls"],
                }
                if sales in trans_validas:
                    if nuevo not in trans_validas[sales]:
                        raise HTTPException(400, f"Transición no permitida: {sales} → {nuevo}")
                else:
                    permitidos = ["New Lead","First Contact","Follow Up","Interested","Lost","Appointment Scheduled","No Answer","canceled treatment","Booked Calls","At reception","International line"]
                    if nuevo not in permitidos:
                        raise HTTPException(400, f"No puedes mover este lead a '{nuevo}'")
                updates["sales_status"] = nuevo
                nota = f"Asesor: {sales} → {nuevo}"
                if nuevo == "Appointment Scheduled":
                    medilink = data.medilink_numero or lead.get("medilink_numero")
                    if not medilink: raise HTTPException(400, "Número de paciente (medilink) obligatorio")
                    updates["appointment_status"] = "Scheduled"
                    updates["medical_status"] = "Pending Evaluation"
                    updates["cita_confirmada"] = False
                    if data.medilink_numero: updates["medilink_numero"] = data.medilink_numero
                    if data.doctor_id: updates["doctor_id"] = data.doctor_id
                    if data.treatment_date: updates["treatment_date"] = data.treatment_date
                    sync_agenda(conn, data.lead_id, data.treatment_date, data.doctor_id, 'Scheduled')
                elif nuevo == "Lost":
                    if not data.rejection_reason: raise HTTPException(400, "Se requiere razón de pérdida")
                    updates["rejection_reason"] = data.rejection_reason
                    updates["appointment_status"] = None
                    updates["medical_status"] = None
                    delete_from_agenda(conn, data.lead_id)
            elif data.crear_control:
                pass
            elif not data.comentario:
                raise HTTPException(400, "No hay cambios válidos para el asesor")

        # ========== DOCTOR ==========
        elif rol == "doctor":
            if data.treatment_end_date and med == "In Treatment":
                updates["treatment_end_date"] = data.treatment_end_date
                nota = f"Fecha fin actualizada: {data.treatment_end_date}"
            elif data.appointment_status == "Canceled" and sales == "Appointment Scheduled":
                updates["sales_status"] = "canceled treatment"
                updates["appointment_status"] = "Canceled"
                updates["cita_confirmada"] = False
                updates["medical_status"] = None
                nota = "Cita cancelada por doctor"
                delete_from_agenda(conn, data.lead_id)
            elif data.appointment_status == "No Show" and sales == "Appointment Scheduled":
                updates["sales_status"] = "canceled treatment"
                updates["appointment_status"] = "No Show"
                updates["cita_confirmada"] = False
                updates["medical_status"] = None
                nota = "No Show marcado por doctor"
                delete_from_agenda(conn, data.lead_id)
            elif data.appointment_status == "Attended" and sales == "Appointment Scheduled":
                updates["appointment_status"] = "Attended"
                if not med:
                    updates["medical_status"] = "Pending Evaluation"
                nota = "Paciente asistió a consulta"
                update_agenda_estado(conn, data.lead_id, 'Attended')
            elif data.treatment_confirmed is True and sales == "Treatment Proposal Sent":
                updates["treatment_confirmed"] = True
                nota = "Doctor confirmó aceptación del paciente -> asesor puede agendar inicio"
            elif data.appointment_status == "Rescheduled" and med in ("Treatment Scheduled", "In Treatment"):
                updates["sales_status"] = "Rescheduled Treatment"
                updates["appointment_status"] = "Rescheduled"
                updates["medical_status"] = None
                updates["cita_confirmada"] = False
                nota = "Tratamiento reagendado por doctor -> asesor para confirmar nueva fecha"
                delete_from_agenda(conn, data.lead_id)
            elif data.medical_status == "In Treatment" and med == "Treatment Scheduled":
                if not data.treatment_start_date or not data.treatment_end_date:
                    raise HTTPException(400, "Fechas de inicio y fin del tratamiento obligatorias")
                updates["medical_status"] = "In Treatment"
                updates["appointment_status"] = "Attended"
                updates["treatment_start_date"] = data.treatment_start_date
                updates["treatment_end_date"] = data.treatment_end_date
                nota = f"Tratamiento iniciado: {data.treatment_start_date} -> {data.treatment_end_date}"
                update_agenda_estado(conn, data.lead_id, 'Attended')
            elif med == "In Treatment":
                if data.mark_treatment_completed:
                    updates["medical_status"] = "Treatment Completed"
                    updates["sales_status"] = "Won"
                    updates["appointment_status"] = "Completed"
                    updates["treatment_completed"] = True
                    nota = "Tratamiento completado → Won"
                    delete_from_agenda(conn, data.lead_id)
                elif data.quit_reason:
                    updates["sales_status"] = "Lost"
                    updates["quit_reason"] = data.quit_reason
                    updates["medical_status"] = None
                    nota = f"Abandono: {data.quit_reason}"
                    delete_from_agenda(conn, data.lead_id)
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
                    delete_from_agenda(conn, data.lead_id)
                elif data.appointment_status == "No Show":
                    updates["appointment_status"] = "No Show"
                    updates["sales_status"] = "canceled treatment"
                    updates["medical_status"] = None
                    nota = "No Show en tratamiento -> asesor"
                    delete_from_agenda(conn, data.lead_id)
                elif data.appointment_status == "Canceled":
                    updates["appointment_status"] = "Canceled"
                    updates["sales_status"] = "canceled treatment"
                    updates["medical_status"] = None
                    nota = "Tratamiento cancelado -> asesor"
                    delete_from_agenda(conn, data.lead_id)
                elif not data.comentario:
                    raise HTTPException(400, "Indica acción para el tratamiento activo")
            elif med == "Pending Evaluation":
                if data.appointment_status == "Canceled":
                    updates["appointment_status"] = "Canceled"
                    updates["sales_status"] = "canceled treatment"
                    updates["medical_status"] = None
                    nota = "Cita cancelada por doctor -> asesor"
                    delete_from_agenda(conn, data.lead_id)
                elif data.medical_status == "Consultation Completed":
                    updates["medical_status"] = "Consultation Completed"
                    updates["appointment_status"] = "Completed"
                    nota = "Consulta completada"
                    update_agenda_estado(conn, data.lead_id, 'Completed')
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
                        raise HTTPException(400, "Se requiere razón de rechazo")
                    updates["medical_status"] = "Candidate Rejected"
                    updates["rejection_reason"] = data.rejection_reason
                    updates["sales_status"] = "Lost"
                    nota = f"Rechazado: {data.rejection_reason}"
                    delete_from_agenda(conn, data.lead_id)
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
                        raise HTTPException(400, "Fechas de inicio y fin obligatorias")
                    updates["medical_status"] = "In Treatment"
                    updates["appointment_status"] = "Attended"
                    updates["treatment_start_date"] = data.treatment_start_date
                    updates["treatment_end_date"] = data.treatment_end_date
                    nota = f"Tratamiento iniciado: {data.treatment_start_date} -> {data.treatment_end_date}"
                    update_agenda_estado(conn, data.lead_id, 'Attended')
                elif data.appointment_status == "Rescheduled":
                    updates["sales_status"] = "Rescheduled Treatment"
                    updates["appointment_status"] = "Rescheduled"
                    updates["medical_status"] = None
                    updates["cita_confirmada"] = False
                    nota = "Tratamiento reagendado por doctor -> asesor"
                    delete_from_agenda(conn, data.lead_id)
                elif data.appointment_status == "No Show":
                    updates["appointment_status"] = "No Show"
                    updates["sales_status"] = "canceled treatment"
                    updates["medical_status"] = None
                    nota = "No Show en inicio de tratamiento -> asesor"
                    delete_from_agenda(conn, data.lead_id)
                elif data.appointment_status == "Canceled":
                    updates["appointment_status"] = "Canceled"
                    updates["sales_status"] = "canceled treatment"
                    updates["medical_status"] = None
                    nota = "Tratamiento cancelado por doctor -> asesor"
                    delete_from_agenda(conn, data.lead_id)
            elif data.rejection_reason and not data.medical_status:
                updates["medical_status"] = "Candidate Rejected"
                updates["rejection_reason"] = data.rejection_reason
                updates["sales_status"] = "Lost"
                nota = f"Rechazado: {data.rejection_reason}"
                delete_from_agenda(conn, data.lead_id)
            elif data.crear_control:
                pass
            elif not data.comentario:
                raise HTTPException(400, "No hay cambios válidos para el doctor")

        # ========== SOPORTE ==========
        elif rol == "soporte":
            if data.sales_status: updates["sales_status"] = data.sales_status
            if data.appointment_status: updates["appointment_status"] = data.appointment_status
            if data.medical_status: updates["medical_status"] = data.medical_status
            if data.doctor_id is not None: updates["doctor_id"] = data.doctor_id
            if data.treatment_date: updates["treatment_date"] = data.treatment_date
            if data.treatment_start_date: updates["treatment_start_date"] = data.treatment_start_date
            if data.treatment_end_date: updates["treatment_end_date"] = data.treatment_end_date
            if data.rejection_reason: updates["rejection_reason"] = data.rejection_reason
            if data.next_treatment_date: updates["next_treatment_date"] = data.next_treatment_date
            if data.quit_reason: updates["quit_reason"] = data.quit_reason
            if data.medilink_numero: updates["medilink_numero"] = data.medilink_numero
            if data.cita_confirmada is not None: updates["cita_confirmada"] = data.cita_confirmada
            if data.treatment_confirmed is not None: updates["treatment_confirmed"] = data.treatment_confirmed
            if data.pipeline: updates["pipeline"] = data.pipeline
            if data.mark_treatment_completed is not None: updates["treatment_completed"] = data.mark_treatment_completed
            nota = "Actualización por soporte"
            if data.treatment_date and data.doctor_id and updates.get("sales_status") == "Appointment Scheduled":
                sync_agenda(conn, data.lead_id, data.treatment_date, data.doctor_id, 'Scheduled')
        else:
            raise HTTPException(400, "Rol no autorizado")

        if not updates and not data.comentario and not data.crear_control:
            raise HTTPException(400, "No hay cambios para aplicar")

        # Aplicar updates (incluyendo last_contact_date)
        if updates:
            updates["fecha_actualizacion"] = "now"
            updates["last_contact_date"] = "now"   # ← SE AGREGA AQUÍ
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

        # Comentario sin cambios de estado (también actualiza last_contact_date)
        if data.comentario:
            ts = now.strftime("[%Y-%m-%d %H:%M]")
            nuevo_com = f"{ts} [{rol.upper()}] {data.comentario}"
            prev = lead.get("comentarios") or ""
            cur.execute("UPDATE leads SET comentarios=%s, last_contact_date = CURRENT_DATE WHERE id=%s",
                        ((prev + "\n" + nuevo_com).strip(), data.lead_id))

        if data.crear_control:
            c = data.crear_control
            fecha_ctrl = c.fecha_control if hasattr(c, 'fecha_control') else None
            tipo_ctrl = c.tipo if hasattr(c, 'tipo') else "Control"
            desc_ctrl = c.descripcion if hasattr(c, 'descripcion') else ""
            doc_ctrl = c.doctor_id if hasattr(c, 'doctor_id') else None
            cur.execute(
                "INSERT INTO controles (lead_id,tipo,descripcion,fecha_control,doctor_id,asesor_id,estado) "
                "VALUES (%s,%s,%s,%s,%s,%s,'Agendado') RETURNING id",
                (data.lead_id, tipo_ctrl, desc_ctrl, fecha_ctrl, doc_ctrl,
                 data.usuario_id if rol == "asesor" else None)
            )
            control_id = cur.fetchone()[0]
            nota = nota or f"Control agendado: {tipo_ctrl}"

        conn.commit(); cur.close()
        return {
            "id": updated["id"],
            "sales_status": updated.get("sales_status"),
            "appointment_status": updated.get("appointment_status"),
            "medical_status": updated.get("medical_status"),
            "treatment_confirmed": updated.get("treatment_confirmed", False),
            "message": nota,
            "control_id": control_id
        }
    finally:
        release_db(conn)

# ========== CREAR LEAD ==========
@app.post("/leads")
def crear_lead(data: LeadCreate):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
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

        print("📦 data.pipeline:", repr(data.pipeline))
        print("📦 data completo:", data.dict())


        cur2.execute(
            "INSERT INTO leads (nombre,telefono,email,categoria,canal,genero,ciudad,notas,"
            "sales_status,asesor_id,doctor_id,creado_por,pipeline,last_contact_date,admission_date) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE,CURRENT_DATE) RETURNING id",
            (data.nombre, data.telefono, data.email, data.categoria, data.canal,
            data.genero, data.ciudad, data.notas,
            data.sales_status_inicial or "New Lead",
            asesor_id, data.doctor_id, data.creado_por, data.pipeline)
        )
        lead_id = cur2.fetchone()[0]
        conn.commit(); cur.close(); cur2.close()
        return {"id": lead_id, "message": "Lead creado"}
    finally:
        release_db(conn)

# ========== HISTORIAL, AGENDA, CONTROLES ==========
@app.get("/leads/{lead_id}/historial")
def get_historial(lead_id: int):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT h.*, u.nombre FROM historial_estados h "
            "LEFT JOIN usuarios u ON h.cambiado_por=u.id "
            "WHERE h.lead_id=%s ORDER BY h.fecha DESC", (lead_id,)
        )
        hist = cur.fetchall(); cur.close()
        return {"historial": hist}
    finally:
        release_db(conn)

@app.get("/agenda")
def get_agenda():
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT l.id AS lead_id, l.nombre AS paciente,
                COALESCE(l.treatment_date, l.treatment_start_date) AS fecha_inicio,
                l.treatment_start_date, l.treatment_end_date,
                l.sales_status, l.medical_status, l.appointment_status,
                d.nombre AS doctor_nombre, d.id AS doctor_id,
                CASE
                    WHEN l.medical_status IN ('In Treatment','Treatment Scheduled') THEN 'Tratamiento'
                    WHEN l.medical_status = 'Pending Evaluation' THEN 'Consulta'
                    ELSE 'Cita'
                END AS tipo,
                COALESCE(l.appointment_status,'Reservado') AS estado
            FROM leads l
            LEFT JOIN usuarios d ON l.doctor_id=d.id
            WHERE l.doctor_id IS NOT NULL
              AND l.sales_status NOT IN ('Won','Lost')
              AND (l.treatment_date IS NOT NULL OR l.treatment_start_date IS NOT NULL)
            ORDER BY COALESCE(l.treatment_start_date, l.treatment_date) ASC
        """)
        slots = cur.fetchall(); cur.close()
        return {"slots": slots}
    finally:
        release_db(conn)

@app.get("/leads/{lead_id}/controles")
def get_controles(lead_id: int):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT c.*, d.nombre AS doctor_nombre FROM controles c "
            "LEFT JOIN usuarios d ON c.doctor_id=d.id "
            "WHERE c.lead_id=%s ORDER BY c.fecha_creacion DESC", (lead_id,)
        )
        controles = cur.fetchall(); cur.close()
        return {"controles": controles}
    finally:
        release_db(conn)

# ========== GOOGLE SHEETS ==========
@app.post("/google/lead")
def recibir_lead_google(lead: LeadGoogle):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        asesor_id = row[0] if row else None
        cur.execute(
            "INSERT INTO leads (nombre,telefono,email,categoria,canal,sales_status,asesor_id,creado_por,last_contact_date,admission_date) "
            "VALUES (%s,%s,%s,%s,%s,'New Lead',%s,%s,CURRENT_DATE,CURRENT_DATE) RETURNING id",
            (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal, asesor_id, lead.source)
        )
        result = cur.fetchone()
        conn.commit(); cur.close()
        return {"id": result[0], "message": "Lead creado desde Google Sheets"}
    finally:
        release_db(conn)

# ========== HEALTH ==========
@app.get("/health")
def health():
    conn = get_db()
    try:
        release_db(conn)
        return {"status": "ok", "version": "9.6.0"}
    except:
        return {"status": "error"}