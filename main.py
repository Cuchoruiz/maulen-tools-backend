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

def enviar_plantilla_confirmacion(numero, nombre_cliente, telefono_cliente, producto, direccion, total):
    """Envía la plantilla aprobada 'confirmacion_de_pedidos' con 5 variables."""
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
                        {"type": "text", "text": nombre_cliente},
                        {"type": "text", "text": telefono_cliente},
                        {"type": "text", "text": producto},
                        {"type": "text", "text": direccion},
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
            # Si el mensaje viene de un botón, el texto puede ser el payload del botón
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
    nombre: str = Query(None),
    telefono: str = Query(None),
    producto: str = Query(None),
    total: str = Query(None),
    direccion: str = Query(None)
):
    # Si vienen los parámetros de plantilla, usar plantilla (5 variables)
    if nombre and producto and total and direccion:
        telefono_cliente = telefono if telefono else numero
        result = enviar_plantilla_confirmacion(numero, nombre, telefono_cliente, producto, direccion, total)
        return result
    # Si no, enviar texto libre
    if mensaje:
        return enviar_whatsapp(numero, mensaje)
    return {"error": "Faltan parámetros: usa 'mensaje' para texto libre o 'nombre','telefono','producto','total','direccion' para plantilla."}
