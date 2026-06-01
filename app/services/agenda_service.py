from psycopg2.extras import RealDictCursor
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

LOCAL_TZ = ZoneInfo("America/Bogota")

def get_agenda(conn, doctor_id=None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT
            l.id AS lead_id,
            l.nombre AS paciente,
            l.treatment_date AS fecha_inicio,
            NULL AS fecha_fin,
            l.appointment_status AS estado,
            'Consulta' AS tipo,
            d.nombre AS doctor_nombre,
            d.id AS doctor_id
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id = d.id
        WHERE l.sales_status = 'Appointment Scheduled'
          AND l.cita_confirmada = True
          AND l.treatment_date IS NOT NULL
    """
    params = []
    if doctor_id is not None:
        query += " AND l.doctor_id = %s"
        params.append(doctor_id)
    query += " ORDER BY l.treatment_date ASC"

    cur.execute(query, params)
    slots = cur.fetchall()
    cur.close()

    # Convertir fechas a texto ISO 8601 con Z (UTC)
    for slot in slots:
        if slot["fecha_inicio"]:
            slot["fecha_inicio"] = slot["fecha_inicio"].isoformat() + "Z"
        if slot["fecha_fin"]:
            slot["fecha_fin"] = slot["fecha_fin"].isoformat() + "Z"

    return {"slots": slots}