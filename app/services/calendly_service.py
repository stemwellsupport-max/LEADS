# app/services/calendly_service.py
import hashlib
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime
from ..services.lead_service import create_lead  # opcional si quieres reutilizar

def get_or_create_lead(conn, nombre: str, email: str, telefono: str = ""):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Buscar por email o teléfono (igual que tu lógica actual)
    if email:
        cur.execute("SELECT * FROM leads WHERE email=%s AND email<>''", (email,))
        lead = cur.fetchone()
        if lead:
            cur.close()
            return lead
    if telefono:
        cur.execute("SELECT * FROM leads WHERE telefono=%s AND telefono<>''", (telefono,))
        lead = cur.fetchone()
        if lead:
            cur.close()
            return lead

    # No existe → crear uno nuevo (lógica simplificada, puedes llamar a create_lead de tu servicio)
    # Asignar asesor aleatorio
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    asesor_id = row["id"] if row else None

    cur.execute("""
        INSERT INTO leads (nombre, telefono, email, sales_status, asesor_id, creado_por)
        VALUES (%s, %s, %s, 'New Lead', %s, 'calendly')
        RETURNING *
    """, (nombre, telefono, email, asesor_id))
    lead = cur.fetchone()
    conn.commit()
    cur.close()
    return lead

def mapear_doctor_desde_evento(conn, event_name: str):
    """
    Según el nombre del evento de Calendly, decide qué doctor asignar.
    Puedes hacer un mapeo fijo o consultar la BD.
    Por ahora, un mapeo simple:
    """
    mapping = {
        "Consulta inicial": "doctor@stemwell.com",   # email del doctor
        "Tratamiento capilar": "otro@stemwell.com",
        # ...
    }
    email_doctor = mapping.get(event_name)
    if email_doctor:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id FROM usuarios WHERE email=%s AND rol='doctor' AND activo=true", (email_doctor,))
        doc = cur.fetchone()
        cur.close()
        if doc:
            return doc["id"]
    # Si no hay mapeo, asigna el primer doctor disponible
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id FROM usuarios WHERE rol='doctor' AND activo=true ORDER BY id LIMIT 1")
    doc = cur.fetchone()
    cur.close()
    return doc["id"] if doc else None

def crear_cita_desde_calendly(conn, lead_id: int, doctor_id: int, start_time: str, end_time: str, event_id: str, event_name: str):
    cur = conn.cursor()
    # Determinar tipo
    tipo = "Consulta" if "consulta" in event_name.lower() else "Tratamiento"
    cur.execute("""
        INSERT INTO agenda_doctor (lead_id, doctor_id, fecha_inicio, fecha_fin, estado, tipo, creado_por, evento_externo_id)
        VALUES (%s, %s, %s, %s, 'Scheduled', %s, 'calendly', %s)
        ON CONFLICT (evento_externo_id) DO NOTHING
        RETURNING id
    """, (lead_id, doctor_id, start_time, end_time, tipo, event_id))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    if result:
        # Actualizar resumen en leads para que tu frontend siga funcionando
        actualizar_resumen_cita(conn, lead_id)
    return result[0] if result else None

def actualizar_resumen_cita(conn, lead_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT fecha_inicio, estado, doctor_id
        FROM agenda_doctor
        WHERE lead_id = %s AND estado NOT IN ('Canceled','Completed')
        ORDER BY fecha_inicio ASC LIMIT 1
    """, (lead_id,))
    cita = cur.fetchone()
    if cita:
        cur.execute("""
            UPDATE leads
            SET treatment_date = %s,
                appointment_status = %s,
                doctor_id = COALESCE(doctor_id, %s),
                sales_status = CASE
                    WHEN sales_status NOT IN ('Won','Lost') THEN 'Appointment Scheduled'
                    ELSE sales_status
                END,
                medical_status = CASE
                    WHEN medical_status IS NULL THEN 'Pending Evaluation'
                    ELSE medical_status
                END
            WHERE id = %s
        """, (cita["fecha_inicio"], cita["estado"], cita["doctor_id"], lead_id))
    else:
        cur.execute("""
            UPDATE leads
            SET treatment_date = NULL,
                appointment_status = NULL
            WHERE id = %s
        """, (lead_id,))
    conn.commit()
    cur.close()

def cancelar_cita_calendly(conn, event_id: str):
    cur = conn.cursor()
    cur.execute("""
        UPDATE agenda_doctor
        SET estado = 'Canceled', fecha_actualizacion = NOW()
        WHERE evento_externo_id = %s AND estado != 'Canceled'
        RETURNING lead_id
    """, (event_id,))
    lead_id = cur.fetchone()
    if lead_id:
        lead_id = lead_id[0]
        # Volver a poner el lead en estado "canceled treatment" si no tiene otras citas activas
        cur.execute("""
            SELECT COUNT(*) FROM agenda_doctor
            WHERE lead_id = %s AND estado NOT IN ('Canceled','Completed')
        """, (lead_id,))
        count = cur.fetchone()[0]
        if count == 0:
            cur.execute("""
                UPDATE leads
                SET sales_status = 'canceled treatment',
                    appointment_status = NULL,
                    treatment_date = NULL
                WHERE id = %s
            """, (lead_id,))
        conn.commit()
    cur.close()