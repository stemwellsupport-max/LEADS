from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import BookedCallCreate, BookedCallUpdate
from psycopg2.extras import RealDictCursor
from typing import Optional

router = APIRouter(prefix="/booked-calls", tags=["BookedCalls"])

@router.post("")
def crear_booked_call(data: BookedCallCreate, conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, nombre, sales_status FROM leads WHERE id=%s", (data.lead_id,))
    lead = cur.fetchone()
    if not lead:
        raise HTTPException(404, "Lead no encontrado")
    cur.execute(
        "INSERT INTO booked_calls (lead_id,asesor_id,fecha_llamada,tipo,notas,estado) "
        "VALUES (%s,%s,%s,%s,%s,'Pendiente') RETURNING id",
        (data.lead_id, data.asesor_id, data.fecha_llamada, data.tipo or "Llamada", data.notas or "")
    )
    result = cur.fetchone()
    cur.execute("UPDATE leads SET sales_status='Booked Calls', fecha_actualizacion=CURRENT_TIMESTAMP WHERE id=%s", (data.lead_id,))
    conn.commit()
    cur.close()
    return {"id": result["id"], "message": "Llamada reservada", "lead_nombre": lead["nombre"]}

@router.get("")
def listar_booked_calls(asesor_id: Optional[int] = None, conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if asesor_id:
        cur.execute("""
            SELECT bc.*, l.nombre AS lead_nombre, l.telefono AS lead_telefono, a.nombre AS asesor_nombre
            FROM booked_calls bc
            JOIN leads l ON bc.lead_id=l.id
            JOIN usuarios a ON bc.asesor_id=a.id
            WHERE bc.asesor_id=%s
            ORDER BY bc.fecha_llamada DESC
        """, (asesor_id,))
    else:
        cur.execute("""
            SELECT bc.*, l.nombre AS lead_nombre, l.telefono AS lead_telefono, a.nombre AS asesor_nombre
            FROM booked_calls bc
            JOIN leads l ON bc.lead_id=l.id
            JOIN usuarios a ON bc.asesor_id=a.id
            ORDER BY bc.fecha_llamada DESC
        """)
    calls = cur.fetchall()
    cur.close()
    return {"calls": calls}

@router.put("/{call_id}")
def actualizar_booked_call(call_id: int, data: BookedCallUpdate, conn=Depends(get_connection)):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM booked_calls WHERE id=%s", (call_id,))
    call = cur.fetchone()
    if not call:
        raise HTTPException(404, "Llamada no encontrada")
    updates = {}
    if data.estado: updates["estado"] = data.estado
    if data.notas is not None: updates["notas"] = data.notas
    if data.fecha_llamada: updates["fecha_llamada"] = data.fecha_llamada
    if data.tipo: updates["tipo"] = data.tipo
    if updates:
        set_parts = [f"{k}=%s" for k in updates]
        set_parts.append("actualizado_en=CURRENT_TIMESTAMP")
        values = list(updates.values()) + [call_id]
        cur.execute(f"UPDATE booked_calls SET {', '.join(set_parts)} WHERE id=%s RETURNING *", values)
    conn.commit()
    cur.close()
    return {"message": "Llamada actualizada"}

@router.delete("/{call_id}")
def eliminar_booked_call(call_id: int, conn=Depends(get_connection)):
    cur = conn.cursor()
    cur.execute("DELETE FROM booked_calls WHERE id=%s", (call_id,))
    conn.commit()
    cur.close()
    return {"message": "Llamada eliminada"}