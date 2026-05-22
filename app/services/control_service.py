from psycopg2.extras import RealDictCursor

def get_controles(conn, lead_id: int):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT c.*,d.nombre AS doctor_nombre FROM controles c "
        "LEFT JOIN usuarios d ON c.doctor_id=d.id "
        "WHERE c.lead_id=%s ORDER BY c.fecha_creacion DESC",
        (lead_id,)
    )
    controles = cur.fetchall()
    cur.close()
    return {"controles": controles}