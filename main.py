import os
import requests
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()

# ---------- CONFIGURACIÓN DE WHATSAPP CLOUD API ----------
META_VERSION = os.getenv("META_VERSION", "v25.0")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "1173835815815400")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "maulen_webhook_2026")
WHATSAPP_API_URL = f"https://graph.facebook.com/{META_VERSION}/{PHONE_NUMBER_ID}/messages"

# ---------- MODO DRY RUN ----------
DRY_RUN = os.getenv("DRY_RUN_DROPI", "true").lower() == "true"

# ---------- ALMACENAMIENTO TEMPORAL (solo para pruebas) ----------
pending_confirmations = {}

# ---------- UTILIDADES ----------
def normalize_phone(phone):
    clean = phone.replace('@c.us', '').replace('@lid', '').replace('@g.us', '').replace('+', '').replace(' ', '').strip()
    if clean.startswith('56'):
        return clean
    if clean.startswith('9'):
        return '56' + clean
    return '56' + clean

# ---------- ENVÍO DE WHATSAPP (plantilla real) ----------
def enviar_plantilla_confirmacion(numero, nombre, apellido, tienda, telefono_cli, producto, calle, comuna, region, total):
    """Envía la plantilla 'confirmacion_de_pedidos' con los 9 parámetros."""
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
            "language": {"code": "es"},  # ← CORREGIDO a "es"
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
    """Envía un mensaje de texto libre."""
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

# ---------- WEBHOOK DE WHATSAPP ----------
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
            text = None
            if msg.get("type") == "button":
                text = msg.get("button", {}).get("payload", "") or msg.get("button", {}).get("text", "")
            elif msg.get("type") == "text":
                text = msg.get("text", {}).get("body", "")
            if text:
                print(f"📩 WhatsApp recibido de {phone}: {text}")
                await procesar_respuesta_whatsapp(phone, text)
        return {"status": "received"}
    except Exception as e:
        return {"error": str(e)}

async def procesar_respuesta_whatsapp(phone, text):
    phone_norm = normalize_phone(phone)
    text_clean = text.strip().upper()
    if text_clean in ["1", "SI"]:
        pedido = pending_confirmations.get(phone_norm)
        if pedido:
            if DRY_RUN:
                print(f"🔒 DRY RUN: Pedido {pedido['order_id']} habría sido confirmado para {phone_norm}")
            mensaje = "Perfecto, tu pedido fue confirmado. Lo prepararemos para despacho."
            enviar_whatsapp(phone_norm, mensaje)
            pending_confirmations[phone_norm]["estado"] = "confirmado_por_whatsapp"
        else:
            enviar_whatsapp(phone_norm, "No encontramos tu pedido pendiente. Por favor, contáctanos directamente.")
    elif text_clean in ["2", "NO", "NO, MODIFICAR DATOS"]:
        pedido = pending_confirmations.get(phone_norm)
        if pedido:
            pending_confirmations[phone_norm]["estado"] = "requiere_revision"
        enviar_whatsapp(phone_norm, "Gracias, revisaremos tus datos antes de despachar tu pedido.")
    elif text_clean == "3":
        enviar_whatsapp(phone_norm, "Por favor, responde con tu nueva dirección completa.")
    else:
        enviar_whatsapp(phone_norm, "No entendí tu respuesta. Responde: 1 para confirmar, 2 para cancelar, 3 para cambiar dirección.")

# ---------- ENDPOINT DE ENVÍO ----------
@app.get("/send_whatsapp")
async def send_whatsapp(
    numero: str = Query(...),
    mensaje: str = Query(""),
    order_id: str = Query(None),
    nombre: str = Query(None),
    apellido: str = Query(""),
    tienda: str = Query("Casa De Oración Gorbea"),
    telefono: str = Query(None),
    producto: str = Query(None),
    calle: str = Query(""),
    comuna: str = Query(""),
    region: str = Query(""),
    total: str = Query(None)
):
    if nombre and producto and total and telefono:
        phone_norm = normalize_phone(numero)
        pending_confirmations[phone_norm] = {
            "order_id": order_id or "test",
            "nombre": nombre,
            "producto": producto,
            "total": total,
            "estado": "esperando_confirmacion"
        }
        result = enviar_plantilla_confirmacion(
            numero, nombre, apellido, tienda, telefono, producto, calle, comuna, region, total
        )
        return result
    if mensaje:
        return enviar_whatsapp(numero, mensaje)
    return {"error": "Faltan parámetros."}
