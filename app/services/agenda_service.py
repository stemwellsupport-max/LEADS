from psycopg2.extras import RealDictCursor

def get_agenda(conn):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT
            l.id AS lead_id, l.nombre AS paciente,
            l.treatment_date AS fecha_inicio,
            l.treatment_start_date, l.treatment_end_date,
            l.sales_status, l.medical_status, l.appointment_status,
            d.nombre AS doctor_nombre, d.id AS doctor_id,
            CASE
                WHEN l.medical_status = 'In Treatment' THEN 'Tratamiento'
                WHEN l.medical_status = 'Treatment Scheduled' THEN 'Tratamiento'
                WHEN l.medical_status = 'Pending Evaluation' THEN 'Consulta'
                ELSE 'Cita'
            END AS tipo,
            COALESCE(l.appointment_status, 'Reservado') AS estado
        FROM leads l
        LEFT JOIN usuarios d ON l.doctor_id = d.id
        WHERE l.doctor_id IS NOT NULL
          AND l.sales_status NOT IN ('Won','Lost')
          AND (l.treatment_date IS NOT NULL OR l.treatment_start_date IS NOT NULL)
        ORDER BY COALESCE(l.treatment_start_date, l.treatment_date) ASC
    """)
    slots = cur.fetchall()
    cur.close()
    return {"slots": slots}