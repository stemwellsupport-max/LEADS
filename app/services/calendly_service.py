# services/calendly_service.py
from datetime import datetime
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger("stemwell")

def get_or_create_lead(conn, nombre: str, email: str):
    """Busca un lead por email, si no existe lo crea con estado 'New Lead'."""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Buscar por email
    if email:
        cur.execute("SELECT id, nombre, email FROM leads WHERE email = %s", (email,))
        lead = cur.fetchone()
        if lead:
            cur.close()
            return lead

    # Si no hay email o no se encontró, buscar por nombre exacto (opcional, evita duplicados)
    cur.execute("SELECT id, nombre, email FROM leads WHERE nombre = %s", (nombre,))
    lead = cur.fetchone()
    if lead:
        cur.close()
        return lead

    # Crear nuevo lead
    cur2 = conn.cursor()
    # Asignar un asesor aleatorio (o nulo)
    cur2.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur2.fetchone()
    asesor_id = row[0] if row else None

    cur2.execute(
        "INSERT INTO leads (nombre, email, sales_status, asesor_id, creado_por, canal) "
        "VALUES (%s, %s, 'New Lead', %s, 'calendly', 'Calendly') RETURNING id",
        (nombre, email, asesor_id)
    )
    lead_id = cur2.fetchone()[0]
    conn.commit()
    cur2.close()
    cur.close()
    return {"id": lead_id, "nombre": nombre, "email": email}

def mapear_doctor_desde_evento(conn, event_name: str):
    """Convierte el nombre del evento de Calendly a un doctor_id.
    Ejemplo: "Consulta con Dr. García" -> buscar doctor por nombre 'García'."""
    cur = conn.cursor()
    # Extraer posible nombre del doctor del evento (puedes personalizar la lógica)
    # Por ahora, buscamos cualquier doctor cuyo nombre esté contenido en event_name
    cur.execute("SELECT id, nombre FROM usuarios WHERE rol='doctor' AND activo=true")
    doctores = cur.fetchall()
    for doc_id, doc_nombre in doctores:
        if doc_nombre.lower() in event_name.lower():
            cur.close()
            return doc_id
    # Si no se encuentra, retornar None (sin doctor asignado)
    cur.close()
    return None

def crear_cita_desde_calendly(conn, lead_id: int, doctor_id, start_time, end_time, event_id, event_name):
    """Crea un registro en agenda_doctor y actualiza el lead."""
    cur = conn.cursor()
    # Convertir strings ISO a timestamp
    start_ts = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
    end_ts = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

    # Insertar en agenda_doctor
    cur.execute(
        "INSERT INTO agenda_doctor (lead_id, doctor_id, fecha_inicio, fecha_fin, estado, tipo, external_id) "
        "VALUES (%s, %s, %s, %s, 'Scheduled', 'Consulta Calendly', %s) RETURNING id",
        (lead_id, doctor_id, start_ts, end_ts, event_id)
    )
    cita_id = cur.fetchone()[0]

    # Actualizar el lead: appointment_status, treatment_date, sales_status si procede
    cur.execute(
        "UPDATE leads SET appointment_status = 'Scheduled', treatment_date = %s, "
        "sales_status = 'Appointment Scheduled', fecha_actualizacion = CURRENT_TIMESTAMP "
        "WHERE id = %s",
        (start_ts.date(), lead_id)
    )
    conn.commit()
    cur.close()
    return cita_id

def cancelar_cita_calendly(conn, event_id: str):
    """Marca la cita como cancelada en agenda_doctor y actualiza el lead."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE agenda_doctor SET estado = 'Canceled', fecha_actualizacion = CURRENT_TIMESTAMP "
        "WHERE external_id = %s RETURNING lead_id",
        (event_id,)
    )
    row = cur.fetchone()
    if row:
        lead_id = row[0]
        cur.execute(
            "UPDATE leads SET appointment_status = 'Canceled', sales_status = 'canceled treatment' "
            "WHERE id = %s",
            (lead_id,)
        )
    conn.commit()
    cur.close()