# Rosepith Pazarlama Agent - WhatsApp Webhook Sunucusu
# Meta Business API webhook doğrulama ve mesaj alma

import uvicorn
from fastapi import FastAPI, Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from core.config import WHATSAPP_VERIFY_TOKEN
from core.database import log_event
from integrations.whatsapp import parse_webhook, mark_as_read

app = FastAPI(title="Rosepith WhatsApp Webhook")


class NgrokHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response


app.add_middleware(NgrokHeaderMiddleware)


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta'nın webhook doğrulama isteğini karşılar."""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        log_event("whatsapp", "Webhook doğrulandı")
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Doğrulama başarısız")


@app.post("/webhook")
async def receive_webhook(request: Request):
    """Meta'dan gelen WhatsApp mesajlarını işler."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON")

    log_event("whatsapp", f"Webhook alındı: {payload.get('object', '')}")

    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    messages = parse_webhook(payload)
    for msg in messages:
        log_event("whatsapp", f"Mesaj: {msg['from']} -> {msg['text']}")
        # Okundu bildirimi gönder
        if msg.get("id"):
            mark_as_read(msg["id"])
        # Buraya agent yönlendirmesi eklenecek
        _handle_message(msg)

    return {"status": "ok"}


def _handle_message(msg: dict):
    """Gelen WhatsApp mesajını art_director'a iletir."""
    from agents.art_director import handle_whatsapp_message
    import threading

    phone = msg.get("from", "")
    text  = msg.get("text", "").strip()

    if not phone or not text:
        return

    log_event("whatsapp", f"İletiliyor — phone={phone} metin={text[:80]}")
    threading.Thread(
        target=handle_whatsapp_message,
        args=(phone, text),
        daemon=True
    ).start()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "rosepith-whatsapp-webhook"}


if __name__ == "__main__":
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=8000, reload=False)
