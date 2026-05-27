import json
import hmac
import hashlib
from fastapi import APIRouter, Request, Depends, HTTPException
from ..dependencies import get_connection
from ..config import CALENDLY_WEBHOOK_SIGNING_SECRET
from ..services.calendly_service import (
    get_or_create_lead,
    mapear_doctor_desde_evento,
    crear_cita_desde_calendly,
    cancelar_cita_calendly
)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

async def verificar_firma(request: Request):
    """Verifica que el webhook venga realmente de Calendly."""
    signature = request.headers.get("Calendly-Webhook-Signature")
    if not signature:
        raise HTTPException(401, "Firma no presente")
    body = await request.body()
    secret = CALENDLY_WEBHOOK_SIGNING_SECRET.encode()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Firma inválida")
    return json.loads(body)

@router.post("/calendly")
async def calendly_webhook(request: Request, conn = Depends(get_connection)):
    # --- Descomenta la siguiente línea cuando quieras activar la verificación ---
    # payload = await verificar_firma(request)
    # --- Mientras tanto, usamos esta versión (solo para pruebas) ---
    body = await request.body()
    payload = json.loads(body)

    # Puedes dejar este print para depurar, luego lo quitas
    print("=== PAYLOAD RECIBIDO ===")
    print(json.dumps(payload, indent=2))
    print("========================")

    event = payload.get("event")

    if event == "invitee.created":
        invitee = payload["payload"]
        email = invitee.get("email", "")
        name = invitee.get("name", "")
        start_time = invitee["scheduled_event"]["start_time"]
        end_time = invitee["scheduled_event"]["end_time"]
        # Obtenemos el nombre del tipo de evento directamente del campo "name"
        event_name = invitee["scheduled_event"]["name"]
        event_id = invitee["scheduled_event"]["uri"].split("/")[-1]

        lead = get_or_create_lead(conn, name, email)
        doctor_id = mapear_doctor_desde_evento(conn, event_name)
        cita_id = crear_cita_desde_calendly(conn, lead["id"], doctor_id, start_time, end_time, event_id, event_name)

        return {"status": "ok", "lead_id": lead["id"], "cita_id": cita_id}

    elif event == "invitee.canceled":
        event_id = payload["payload"]["scheduled_event"]["uri"].split("/")[-1]
        cancelar_cita_calendly(conn, event_id)
        return {"status": "ok"}

    return {"status": "ignored", "event": event}