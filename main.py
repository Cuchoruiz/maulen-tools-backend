import os
import requests
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()

META_VERSION = os.getenv("META_VERSION", "v25.0")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "1173835815815400")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "maulen_webhook_2026")
WHATSAPP_API_URL = f"https://graph.facebook.com/{META_VERSION}/{PHONE_NUMBER_ID}/messages"
WABA_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "confirmacion_de_pedidos")
TEMPLATE_LANGUAGE = os.getenv("WHATSAPP_TEMPLATE_LANG", "es_CL")

DRY_RUN = os.getenv("DRY_RUN_DROPI", "true").lower() == "true"
DROPI_TOKEN = os.getenv("DROPI_TOKEN", "")

pending_confirmations = {}

class DropiClient:
    BASE = "https://api.dropi.cl/api"

    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://app.dropi.cl",
            "Referer": "https://app.dropi.cl/",
            "User-Agent": "Mozilla/5.0",
            "X-Authorization": f"Bearer {self.token}",
            "X-Captcha-Token": ""
        })

    def _safe_json(self, response):
        try:
            return response.json()
        except Exception:
            return {"raw_text": response.text[:1200] if hasattr(response, "text") else ""}

    def request(self, method: str, path: str, **kwargs):
        if not self.token:
            return {
                "ok": False,
                "status_code": 401,
                "message": "DROPI_TOKEN no configurado",
                "raw": None
            }

        url = path if str(path).startswith("http") else f"{self.BASE}{path}"

        try:
            response = self.session.request(method, url, timeout=25, **kwargs)
            raw = self._safe_json(response)

            return {
                "ok": response.ok,
                "status_code": response.status_code,
                "message": "OK" if response.ok else f"Dropi respondió HTTP {response.status_code}",
                "raw": raw
            }

        except requests.exceptions.Timeout:
            return {
                "ok": False,
                "status_code": 408,
                "message": "Timeout conectando con Dropi",
                "raw": None
            }

        except Exception as e:
            return {
                "ok": False,
                "status_code": 500,
                "message": str(e),
                "raw": None
            }

    def healthcheck(self):
        # Consulta liviana. Si Dropi cambia este endpoint, no rompe la app:
        # solo informa que la conexión no pudo verificarse.
        return self.request("GET", "/orders/myorders", params={"page": 1, "limit": 1})

    def get_order_status(self, order_id: str):
        # Intento 1: endpoint directo por id.
        first = self.request("GET", f"/orders/myorders/{order_id}")
        if first.get("ok"):
            return first

        # Intento 2: búsqueda por parámetro, por si Dropi no soporta /{id}.
        second = self.request("GET", "/orders/myorders", params={"search": order_id, "page": 1, "limit": 10})
        if second.get("ok"):
            return second

        return {
            "ok": False,
            "status_code": first.get("status_code") or second.get("status_code"),
            "message": "No se pudo obtener el estado del pedido en Dropi",
            "raw": {
                "direct": first,
                "search": second
            }
        }

    def confirm_order(self, order_id: str):
        # Acción real. Solo debe llamarse cuando DRY_RUN_DROPI=false.
        return self.request(
            "PUT",
            f"/orders/myorders/{order_id}",
            json={"status": "PENDIENTE"}
        )


def confirm_order_in_dropi(order_id: str) -> dict:
    if not DROPI_TOKEN:
        return {"success": False, "message": "DROPI_TOKEN no configurado", "raw": None}

    try:
        client = DropiClient(DROPI_TOKEN)
        result = client.confirm_order(order_id)
        raw = result.get("raw") or {}

        if result.get("ok") and (raw.get("isSuccess") is True or raw.get("success") is True or raw.get("ok") is True):
            return {"success": True, "message": "Pedido confirmado/liberado en Dropi", "raw": raw}

        if result.get("ok"):
            return {"success": True, "message": "Dropi respondió OK. Revisar raw para confirmar estado final.", "raw": raw}

        return {"success": False, "message": result.get("message", "Dropi no confirmó el pedido"), "raw": result}

    except Exception as e:
        return {"success": False, "message": str(e), "raw": None}

def normalize_phone(phone):
    clean = phone.replace('@c.us', '').replace('@lid', '').replace('@g.us', '').replace('+', '').replace(' ', '').strip()
    if clean.startswith('56'):
        return clean
    if clean.startswith('9'):
        return '56' + clean
    return '56' + clean

def enviar_plantilla_confirmacion(numero, nombre, apellido, tienda, telefono_cli, producto, calle, comuna, region, total):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(numero),
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": TEMPLATE_LANGUAGE},
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
        print(f"🧩 Enviando template: {TEMPLATE_NAME} / idioma: {TEMPLATE_LANGUAGE}")
        print("🧩 Payload template:", payload)
        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=30)
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
        print(f"🧩 Enviando template: {TEMPLATE_NAME} / idioma: {TEMPLATE_LANGUAGE}")
        print("🧩 Payload template:", payload)
        resp = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=30)
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
        print("❌ Error webhook:", str(e))
        return {"error": str(e)}

async def procesar_respuesta_whatsapp(phone, text):
    phone_norm = normalize_phone(phone)
    text_clean = text.strip().upper()

    if text_clean in ["1", "SI"]:
        pedido = pending_confirmations.get(phone_norm)

        if not pedido:
            enviar_whatsapp(phone_norm, "No encontramos tu pedido pendiente. Por favor, contáctanos directamente.")
            return

        dropi_id = pedido.get("dropi_order_id", pedido.get("order_id"))

        if DRY_RUN:
            print(f"🔒 DRY RUN: Pedido {dropi_id} habría sido confirmado para {phone_norm}")
            mensaje = "Perfecto, tu pedido fue confirmado. Lo prepararemos para despacho."
            pending_confirmations[phone_norm]["estado"] = "confirmado_por_whatsapp"

        else:
            resultado = confirm_order_in_dropi(dropi_id)
            print(f"📦 Resultado confirmación Dropi {dropi_id}: {resultado}")

            if resultado["success"]:
                mensaje = "Perfecto, tu pedido fue confirmado. Lo prepararemos para despacho."
                pending_confirmations[phone_norm]["estado"] = "confirmado_por_whatsapp"
            else:
                mensaje = "Recibimos tu confirmación. Revisaremos tu pedido antes del despacho."
                pending_confirmations[phone_norm]["estado"] = "error_confirmacion_dropi"

        enviar_whatsapp(phone_norm, mensaje)

    elif text_clean in ["2", "NO", "NO, MODIFICAR DATOS"]:
        pedido = pending_confirmations.get(phone_norm)

        if pedido:
            pending_confirmations[phone_norm]["estado"] = "requiere_revision"

        enviar_whatsapp(phone_norm, "Gracias, revisaremos tus datos antes de despachar tu pedido.")

    elif text_clean == "3":
        enviar_whatsapp(phone_norm, "Por favor, responde con tu nueva dirección completa.")

    else:
        enviar_whatsapp(phone_norm, "No entendí tu respuesta. Responde: 1 para confirmar, 2 para cancelar, 3 para cambiar dirección.")




# ---------- DROPI SAFE ENDPOINTS ----------
def get_dropi_client():
    return DropiClient(DROPI_TOKEN)


@app.get("/dropi/status")
async def dropi_status():
    base = {
        "success": True,
        "dry_run_dropi": DRY_RUN,
        "has_dropi_token": bool(DROPI_TOKEN),
        "mode": "safe",
        "message": "Dropi configurado en modo seguro. No se ejecutan acciones reales mientras DRY_RUN_DROPI=true."
    }

    if not DROPI_TOKEN:
        return {
            **base,
            "connected": False,
            "dropi_check": None,
            "message": "Falta DROPI_TOKEN en Railway. La app está lista, pero Dropi aún no está conectado."
        }

    check = get_dropi_client().healthcheck()

    return {
        **base,
        "connected": bool(check.get("ok")),
        "dropi_check": {
            "ok": check.get("ok"),
            "status_code": check.get("status_code"),
            "message": check.get("message")
        }
    }


@app.get("/dropi/orders/{order_id}/status")
async def dropi_order_status(order_id: str):
    if not DROPI_TOKEN:
        return {
            "success": False,
            "order_id": order_id,
            "message": "Falta DROPI_TOKEN en Railway.",
            "raw": None
        }

    result = get_dropi_client().get_order_status(order_id)

    return {
        "success": bool(result.get("ok")),
        "order_id": order_id,
        "dry_run_dropi": DRY_RUN,
        "status_code": result.get("status_code"),
        "message": result.get("message"),
        "raw": result.get("raw")
    }


@app.post("/dropi/orders/{order_id}/confirm")
async def dropi_confirm_order(order_id: str):
    if DRY_RUN:
        return {
            "success": True,
            "dry_run": True,
            "order_id": order_id,
            "message": "DRY RUN activo: el pedido NO fue confirmado realmente en Dropi."
        }

    result = confirm_order_in_dropi(order_id)

    return {
        "success": bool(result.get("success")),
        "dry_run": False,
        "order_id": order_id,
        "message": result.get("message"),
        "raw": result.get("raw")
    }
# ---------- FIN DROPI SAFE ENDPOINTS ----------


# ---------- DEBUG WHATSAPP CONFIG ----------
@app.get("/debug/config")
async def debug_config():
    return {
        "meta_version": META_VERSION,
        "phone_number_id": PHONE_NUMBER_ID,
        "waba_id": os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
        "template_name": os.getenv("WHATSAPP_TEMPLATE_NAME", "confirmacion_de_pedidos"),
        "template_language_env": os.getenv("WHATSAPP_TEMPLATE_LANG", ""),
        "template_language_default_expected": "es_CL",
        "whatsapp_api_url": WHATSAPP_API_URL,
        "has_access_token": bool(ACCESS_TOKEN),
        "dry_run_dropi": DRY_RUN,
        "has_dropi_token": bool(DROPI_TOKEN)
    }


@app.get("/debug/routes")
async def debug_routes():
    return {
        "routes": [route.path for route in app.routes]
    }


@app.get("/debug/templates")
async def debug_templates():
    waba_id = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")

    if not waba_id:
        return {
            "success": False,
            "message": "Falta WHATSAPP_BUSINESS_ACCOUNT_ID en Railway Variables"
        }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    url = f"https://graph.facebook.com/{META_VERSION}/{waba_id}/message_templates"
    params = {
        "fields": "name,language,status,category"
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        return resp.json()
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }
# ---------- FIN DEBUG WHATSAPP CONFIG ----------


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
            "dropi_order_id": order_id or "test",
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

    return {
        "error": "Faltan parámetros. Usa 'mensaje' para texto libre o los campos de pedido."
    }
