from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..models.schemas import LeadGoogle

router = APIRouter(prefix="/google", tags=["Google Sheets"])

def limpiar_texto(valor):
    """Elimina/reemplaza caracteres que Latin1 no soporta"""
    if not valor:
        return valor
    # Reemplazar caracteres problemáticos comunes
    reemplazos = {
        '\u2018': "'",   # comilla simple izquierda '
        '\u2019': "'",   # comilla simple derecha '
        '\u201c': '"',   # comilla doble izquierda "
        '\u201d': '"',   # comilla doble derecha "
        '\u2013': '-',   # guión largo –
        '\u2014': '--',  # guión más largo —
        '\u2026': '...', # puntos suspensivos …
        '\u00a0': ' ',   # espacio no rompible
        '\u2020': '',    # daga †
        '\u2021': '',    # doble daga ‡
        '\u2022': '-',   # bullet •
    }
    for k, v in reemplazos.items():
        valor = valor.replace(k, v)
    # Eliminar cualquier otro carácter no Latin1
    try:
        valor.encode('latin-1')
        return valor
    except UnicodeEncodeError:
        return valor.encode('latin-1', errors='replace').decode('latin-1')

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
    
    # Limpiar fechas
    for campo in ["admission_date", "last_contact_date"]:
        valor = getattr(lead, campo, None)
        if valor:
            if " " in valor:
                setattr(lead, campo, valor.split(" ")[0])
            elif "T" in valor:
                setattr(lead, campo, valor.split("T")[0])
    
    # Asignar asesor
    asesor_id = lead.asesor_id if lead.asesor_id else None
    if not asesor_id:
        cur.execute("SELECT id FROM usuarios WHERE rol='asesor' AND activo=true ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        asesor_id = row[0] if row else None
    
    # INSERT con textos limpiados
    cur.execute(
        """INSERT INTO leads 
           (nombre, telefono, email, categoria, canal, genero, 
            sales_status, asesor_id, creado_por, comentarios,
            admission_date, last_contact_date, first_contact)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) 
           RETURNING id""",
        (
            limpiar_texto(lead.nombre),
            limpiar_texto(lead.phone),
            limpiar_texto(lead.email),
            limpiar_texto(lead.categoria),
            limpiar_texto(lead.canal),
            limpiar_texto(lead.genero),
            limpiar_texto(lead.sales_status or 'New Lead'),
            asesor_id,
            limpiar_texto(lead.source),
            limpiar_texto(lead.comentario),
            lead.admission_date,
            lead.last_contact_date,
            limpiar_texto(lead.first_contact)
        )
    )
    
    result = cur.fetchone()
    conn.commit()
    cur.close()
    return {"id": result[0], "message": "Lead creado desde Google Sheets"}