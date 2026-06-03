from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..models.schemas import LeadGoogle

router = APIRouter(prefix="/google", tags=["Google"])

@router.post("/lead")
def recibir_lead_google(lead: LeadGoogle, conn=Depends(get_connection)):
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    asesor_id = row[0] if row else None
    cur.execute(
        "INSERT INTO leads (nombre,telefono,email,categoria,canal,sales_status,asesor_id,creado_por) "
        "VALUES (%s,%s,%s,%s,%s,'New Lead',%s,%s) RETURNING id",
        (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal, asesor_id, lead.source)
    )
    lead_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return {"id": lead_id, "message": "Lead creado desde Google Sheets"}