import os
import requests
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()

META_VERSION = os.getenv("META_VERSION", "v25.0")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "684796621390405")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "maulen_webhook_2026")
WHATSAPP_API_URL = f"https://graph.facebook.com/{META_VERSION}/{PHONE_NUMBER_ID}/messages"

def normalize_phone(phone):
    clean = phone.replace('@c.us', '').replace('@lid', '').replace('@g.us', '').replace('+', '').replace(' ', '').strip()
    if clean.startswith('56'):
        return clean
    if clean.startswith('9'):
        return '56' + clean
    return '56' + clean

def enviar_plantilla_confirmacion(
    numero,        # to
    nombre,        # {{1}}
    apellido,      # {{2}}
    tienda,        # {{3}}
    telefono_cli,  # {{4}}
    producto,      # {{5}}
    calle,         # {{6}}
    comuna,        # {{7}}
    region,        # {{8}}
    total          # {{9}}
):
    """Envía la plantilla 'confirmacion_de_pedidos' con los 9 parámetros correctos."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(numero),
        "type": "template",
        "template": {
            "name": "confirmacion_de_pedidos",
            "language": {"code": "es"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": nombre},
                        {"type": "text", "text": apellido},
                        {"type": "text", "text": tienda},
                        {"type": "text", "text": telefono_cli},
                        {"type": "text", "text": producto},
                        {"type": "text", "text": calle},
                        {"type": "text", "text": comuna},
                        {"type": "text", "text": region},
                        {"type": "text", "text": total}
                    ]
                }
            ]
        }
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def enviar_whatsapp(numero, mensaje):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(numero),
        "type": "text",
        "text": {"body": mensaje}
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")

@app.post("/webhook/whatsapp")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Webhook recibido:", data)
    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        if messages and contacts:
            msg = messages[0]
            contact = contacts[0]
            phone = contact.get("wa_id", "")
            text = msg.get("text", {}).get("body", "")
            if not text and msg.get("type") == "button":
                text = msg.get("button", {}).get("payload", "")
            print(f"📩 WhatsApp recibido de {phone}: {text}")
            await procesar_respuesta_whatsapp(phone, text)
        return {"status": "received"}
    except Exception as e:
        return {"error": str(e)}

async def procesar_respuesta_whatsapp(phone, text):
    phone_norm = normalize_phone(phone)
    text_clean = text.strip().upper()
    if text_clean in ["1", "SI", "SÍ"]:
        enviar_whatsapp(phone_norm, "✅ Confirmación programada. Tu pedido se confirmará en 5 minutos.")
    elif text_clean in ["2", "NO"]:
        enviar_whatsapp(phone_norm, "Pedido cancelado según tu solicitud.")
    elif text_clean == "3":
        enviar_whatsapp(phone_norm, "Por favor, responde con tu nueva dirección completa.")
    else:
        enviar_whatsapp(phone_norm, "No entendí tu respuesta. Responde: 1 para confirmar, 2 para cancelar, 3 para cambiar dirección.")

@app.get("/send_whatsapp")
async def send_whatsapp(
    numero: str = Query(...),
    mensaje: str = Query(""),
    # Parámetros para plantilla (9)
    nombre: str = Query(None),
    apellido: str = Query(""),
    tienda: str = Query("Maulen Store"),
    telefono: str = Query(None),
    producto: str = Query(None),
    calle: str = Query(""),
    comuna: str = Query(""),
    region: str = Query(""),
    total: str = Query(None)
):
    # Si vienen los parámetros mínimos de plantilla, usar plantilla
    if nombre and producto and total and telefono:
        result = enviar_plantilla_confirmacion(
            numero, nombre, apellido, tienda, telefono, producto,
            calle, comuna, region, total
        )
        return result
    # Si no, enviar texto libre
    if mensaje:
        return enviar_whatsapp(numero, mensaje)
    return {"error": "Faltan parámetros. Para plantilla, use: numero, nombre, telefono, producto, total (y opcionales apellido,tienda,calle,comuna,region)."}
