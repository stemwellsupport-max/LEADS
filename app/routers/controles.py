from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..services.lead_service import get_controles

router = APIRouter(prefix="/controles", tags=["Controles"])

@router.get("/lead/{lead_id}")
def controles_lead(lead_id: int, conn=Depends(get_connection)):
    return get_controles(conn, lead_id)