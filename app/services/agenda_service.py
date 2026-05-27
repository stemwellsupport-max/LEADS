from psycopg2.extras import RealDictCursor
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

LOCAL_TZ = ZoneInfo("America/Bogota")

def get_agenda(conn, doctor_id=None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT
            a.id AS cita_id,
            l.id AS lead_id,
            l.nombre AS paciente,
            a.fecha_inicio,
            a.fecha_fin,
            a.estado,
            a.tipo,
            d.nombre AS doctor_nombre,
            d.id AS doctor_id
        FROM agenda_doctor a
        JOIN leads l ON a.lead_id = l.id
        LEFT JOIN usuarios d ON a.doctor_id = d.id
        WHERE a.estado NOT IN ('Canceled', 'Completed')
    """
    params = []
    if doctor_id is not None:
        query += " AND a.doctor_id = %s"
        params.append(doctor_id)
    query += " ORDER BY a.fecha_inicio ASC"

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