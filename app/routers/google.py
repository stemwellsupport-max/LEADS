from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..models.schemas import LeadGoogle

router = APIRouter(prefix="/google", tags=["Google Sheets"])

@router.post("/lead")
def recibir_lead_google(lead: LeadGoogle, conn = Depends(get_connection)):
    cur = conn.cursor()

    # Verificar duplicado por teléfono
    if lead.phone:
        cur.execute("SELECT id, nombre FROM leads WHERE telefono=%s AND telefono<>''", (lead.phone,))
        dup = cur.fetchone()
        if dup:
            cur.close()
            return {"id": dup[0], "duplicado": True, "message": f"Ya existe: {dup[1]}"}

    # Verificar duplicado por email
    if lead.email and lead.email not in ("", "-"):
        cur.execute("SELECT id, nombre FROM leads WHERE email=%s AND email<>''", (lead.email,))
        dup = cur.fetchone()
        if dup:
            cur.close()
            return {"id": dup[0], "duplicado": True, "message": f"Ya existe: {dup[1]}"}

    # Asignar asesor aleatorio
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    asesor_id = row[0] if row else None

    # Estado inicial
    sales_status = lead.sales_status if lead.sales_status else "New Lead"

    # Parsear fechas
    admission_date = None
    if lead.admission_date:
        try:
            from datetime import datetime
            # Intentar varios formatos comunes de Google Sheets
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    admission_date = datetime.strptime(lead.admission_date.strip(), fmt).date()
                    break
                except:
                    pass
        except:
            admission_date = None

    last_contact_date = None
    if lead.last_contact_date:
        try:
            from datetime import datetime
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    last_contact_date = datetime.strptime(lead.last_contact_date.strip(), fmt).date()
                    break
                except:
                    pass
        except:
            last_contact_date = None

    comentario = lead.comentario.strip() if lead.comentario else ""

    cur.execute(
        "INSERT INTO leads "
        "(nombre, telefono, email, categoria, canal, genero, sales_status, "
        "asesor_id, creado_por, notas, admission_date, last_contact_date) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (
            lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal,
            lead.genero, sales_status, asesor_id, lead.source,
            comentario,        # va a columna notas (comentarios los pones con update)
            admission_date,
            last_contact_date
        )
    )
    result = cur.fetchone()
    lead_id = result[0]

    # Guardar comentario en columna comentarios también
    if comentario:
        from datetime import datetime
        ts = datetime.now().strftime("[%Y-%m-%d %H:%M]")
        cur.execute(
            "UPDATE leads SET comentarios=%s WHERE id=%s",
            (f"{ts} [SHEETS] {comentario}", lead_id)
        )

    conn.commit()
    cur.close()
    return {"id": lead_id, "message": "Lead creado desde Google Sheets"}