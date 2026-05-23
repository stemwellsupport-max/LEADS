from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..models.schemas import LeadGoogle

router = APIRouter(prefix="/google", tags=["Google Sheets"])

@router.post("/lead")
def recibir_lead_google(lead: LeadGoogle, conn = Depends(get_connection)):
    cur = conn.cursor()
    
    # Verificar duplicado por email
    if lead.email:
        cur.execute("SELECT id FROM leads WHERE email=%s AND email<>''", (lead.email,))
        if cur.fetchone():
            cur.close()
            return {"duplicado": True, "message": f"Ya existe un lead con email: {lead.email}"}
    
    # Verificar duplicado por teléfono
    if lead.phone:
        cur.execute("SELECT id FROM leads WHERE telefono=%s AND telefono<>''", (lead.phone,))
        if cur.fetchone():
            cur.close()
            return {"duplicado": True, "message": f"Ya existe un lead con teléfono: {lead.phone}"}
    
    # Asignar asesor aleatorio
    cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    asesor_id = row[0] if row else None
    
    # INSERT con comentarios (no notas)
    cur.execute(
        """INSERT INTO leads 
           (nombre, telefono, email, categoria, canal, genero, 
            sales_status, asesor_id, creado_por, comentarios,
            admission_date, last_contact_date)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) 
           RETURNING id""",
        (lead.nombre, lead.phone, lead.email, lead.categoria, lead.canal,
         lead.genero, lead.sales_status or 'New Lead', asesor_id, lead.source,
         lead.comentario, lead.admission_date, lead.last_contact_date)
    )
    
    result = cur.fetchone()
    conn.commit()
    cur.close()
    return {"id": result[0], "message": "Lead creado desde Google Sheets"}