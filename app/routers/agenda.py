from fastapi import APIRouter, Depends
from ..dependencies import get_connection
from ..services.agenda_service import get_agenda

router = APIRouter(prefix="/agenda", tags=["Agenda"])

@router.get("")
def agenda(conn = Depends(get_connection)):
    return get_agenda(conn)