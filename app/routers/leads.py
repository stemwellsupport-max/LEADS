import logging
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_connection
from ..models.schemas import LeadCreate, UpdateStatus
from ..services.lead_service import (
    get_leads_for_user,
    create_lead,
    update_lead_status,
    get_history,
    get_controles,
    transferir_lead,
)

router = APIRouter(prefix="/leads", tags=["Leads"])
logger = logging.getLogger("stemwell")

@router.get("/usuario/{usuario_id}")
def leads_por_usuario(usuario_id: int, estado: str = None, conn=Depends(get_connection)):
    try:
        return get_leads_for_user(conn, usuario_id, estado)
    except ValueError as e:
        raise HTTPException(404, str(e))

@router.post("")
def crear_lead(data: LeadCreate, conn=Depends(get_connection)):
    try:
        lead_id = create_lead(conn, data)
        return {"id": lead_id, "message": "Lead creado"}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.put("/estado")
def cambiar_estado(data: UpdateStatus, conn=Depends(get_connection)):
    logger.warning(f"PUT /leads/estado | lead={data.lead_id} user={data.usuario_id}")
    try:
        result = update_lead_status(conn, data.lead_id, data.usuario_id, data)
        return result
    except ValueError as e:
        logger.error(f"400: {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"500: {e}", exc_info=True)
        raise HTTPException(500, f"Error interno: {str(e)}")

@router.put("/{lead_id}/transferir")
def transferir(lead_id: int, data: dict, conn=Depends(get_connection)):
    nuevo_asesor_id = data.get("nuevo_asesor_id")
    usuario_id = data.get("usuario_id")
    if not nuevo_asesor_id:
        raise HTTPException(400, "nuevo_asesor_id es obligatorio")
    try:
        return transferir_lead(conn, lead_id, int(nuevo_asesor_id), usuario_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.get("/{lead_id}/historial")
def historial(lead_id: int, conn=Depends(get_connection)):
    return get_history(conn, lead_id)

@router.get("/{lead_id}/controles")
def controles(lead_id: int, conn=Depends(get_connection)):
    return get_controles(conn, lead_id)