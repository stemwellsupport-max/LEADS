from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import LeadCreate, UpdateStatus
from ..services.lead_service import (
    get_leads_for_user,
    create_lead,
    update_lead_status,
    get_history
)

router = APIRouter(prefix="/leads", tags=["Leads"])

@router.get("/usuario/{usuario_id}")
def leads_por_usuario(usuario_id: int, estado: str = None, conn = Depends(get_connection)):
    try:
        return get_leads_for_user(conn, usuario_id, estado)
    except ValueError as e:
        raise HTTPException(404, str(e))

@router.post("")
def crear_lead(data: LeadCreate, conn = Depends(get_connection)):
    try:
        lead_id = create_lead(conn, data)
        return {"id": lead_id, "message": "Lead creado"}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.put("/estado")
def cambiar_estado(data: UpdateStatus, conn = Depends(get_connection)):
    try:
        result = update_lead_status(conn, data.lead_id, data.usuario_id, data)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.get("/{lead_id}/historial")
def historial(lead_id: int, conn = Depends(get_connection)):
    return get_history(conn, lead_id)