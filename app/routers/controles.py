from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..services.control_service import get_controles

router = APIRouter(prefix="/leads", tags=["Controles"])

@router.get("/{lead_id}/controles")
def controles(lead_id: int, conn = Depends(get_connection)):
    return get_controles(conn, lead_id)