import os
import requests
import time
import threading
import uvicorn
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ---------- CONFIGURACIÓN DE WHATSAPP CLOUD API ----------
META_VERSION = os.getenv("META_VERSION", "v25.0")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "684796621390405")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "maulen_webhook_2026")
WHATSAPP_API_URL = f"https://graph.facebook.com/{META_VERSION}/{PHONE_NUMBER_ID}/messages"

# ---------- DROPI ----------
TOKEN = os.environ.get("DROPI_TOKEN", "")

pending_confirmations = {}

def normalize_phone(phone):
    clean = phone.replace('@c.us', '').replace('@lid', '').replace('@g.us', '').replace('+', '').replace(' ', '').strip()
    if clean.startswith('56'):
        return clean
    if clean.startswith('9'):
        return '56' + clean
    return '56' + clean

class DropiClient:
    BASE = "https://api.dropi.cl/api"

    def __init__(self, token):
        self.token = token
        self.session = requests.Session()
        self.session.get("https://app.dropi.cl/auth/login", headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        })
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-419,es;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://app.dropi.cl",
            "Referer": "https://app.dropi.cl/",
            "Priority": "u=1, i",
            "Sec-Ch-Ua": '"Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Sec-Gpc": "1",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "X-Authorization": f"Bearer {self.token}",
            "X-Captcha-Token": ""
        })

    def get_all_products(self, keyword="", max_pages=30):
        all_products = []
        for page in range(max_pages):
            payload = {
                "pageSize": 50, "startData": page * 50,
                "privated_product": False, "userVerified": False,
                "favorite": False, "with_collection": True,
                "get_stock": False, "no_count": True,
                "search_type": "simple", "keywords": keyword, "country": "CHILE"
            }
            resp = self.session.post(f"{self.BASE}/products/v4/index", json=payload)
            data = resp.json()
            if not data.get("isSuccess") or not data.get("objects"):
                break
            all_products.extend(data["objects"])
            time.sleep(0.8)
        return all_products

    def get_order_detail(self, order_id):
        resp = self.session.get(f"{self.BASE}/orders/myorders/{order_id}")
        return resp.json()

    def confirm_order(self, order_id):
        resp = self.session.put(f"{self.BASE}/orders/myorders/{order_id}", json={"status": "PENDIENTE"})
        return resp.json()

client = DropiClient(TOKEN)

def calcular_score(p):
    try:
        sale = p.get("sale_price") or 0
        suggested = p.get("suggested_price") or 0
        margen = ((suggested - sale) / suggested * 100) if suggested > 0 else 0
        stock = sum((w.get("stock") or 0) for w in (p.get("warehouse_product") or []))
        precio_bueno = 1.0 if 2000 <= suggested <= 50000 else 0.5
        categorias = [c.get("name", "") for c in (p.get("categories") or [])]
        cat_score = 1.0 if any(c in {"Hogar","Tecnología","Cocina","Belleza","Salud","Aseo"} for c in categorias) else 0.3
        score = (0.45 * min(margen/100, 1) + 0.20 * min(stock/100, 1) + 0.15 * precio_bueno + 0.20 * cat_score) * 100
        return round(score, 1)
    except:
        return 0.0

def validar_direccion(direccion, comuna=None, region=None):
    if not direccion or direccion.strip() == "":
        return False, "Dirección vacía"
    query = direccion.strip()
    if comuna:
        query += f", {comuna}"
    if region:
        query += f", {region}"
    query += ", Chile"
    url = "https://geocode.search.hereapi.com/v1/geocode"
    params = {
        "q": query,
        "apiKey": "mCzL45Y5zvzt2iu4T0wU7FVk2cmWsPngTOJAjTsySys",
        "in": "countryCode:CHL"
    }
    try:
        resp = requests.get(url, params=params)
        data = resp.json()
        if "items" in data and len(data["items"]) > 0:
            result = data["items"][0]
            score = result.get("scoring", {}).get("queryScore", 0)
            address = result.get("address", {})
            label = address.get("label", query)
            if score > 0.7:
                return True, f"Válida (score {score}): {label}"
            elif score > 0.4:
                return False, f"Aproximada (score {score}): {label}"
            else:
                return False, f"Poco precisa (score {score}): {label}"
        else:
            return False, "Dirección no encontrada"
    except Exception as e:
        return False, f"Error: {str(e)}"

# ---------- ENVÍO DE WHATSAPP (API OFICIAL) ----------
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

def enviar_plantilla_confirmacion(numero, customer_name, product_name, total, address):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(numero),
        "type": "template",
        "template": {
            "name": "confirmacion_pedido",
            "language": {"code": "es"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": customer_name},
                        {"type": "text", "text": product_name},
                        {"type": "text", "text": total},
                        {"type": "text", "text": address}
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

# ---------- ENDPOINTS ----------
@app.get("/login")
async def login():
    return {"success": True}

@app.get("/products/{keyword}")
async def get_products(keyword: str):
    if not client.token:
        return {"success": False, "message": "Token no configurado"}
    try:
        products = client.get_all_products(keyword)
        for p in products:
            p["score"] = calcular_score(p)
        products.sort(key=lambda p: p.get("score", 0) or 0, reverse=True)
        return {"success": True, "products": products[:50]}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/validate_address")
async def validate_address(direccion: str = Query(...), comuna: str = None, region: str = None):
    valido, mensaje = validar_direccion(direccion, comuna, region)
    return {"valid": valido, "message": mensaje}

@app.get("/simulate_order/{order_id}")
async def simulate_order(order_id: int):
    if not client.token:
        return {"success": False, "message": "Token no configurado"}
    try:
        detail = client.get_order_detail(order_id)
        order_data = detail.get("objects", {})
        if not order_data:
            return {"success": False, "message": "Pedido no encontrado. Respuesta: " + str(detail)}
        direccion = order_data.get("dir", "")
        comuna = order_data.get("city", "")
        region = order_data.get("state", "")
        nombre = order_data.get("name", "")
        telefono = order_data.get("phone", "")
        status = order_data.get("status", "")
        productos = order_data.get("orderdetails", [])
        if productos:
            prod = productos[0]
            nombre_prod = prod.get("product", {}).get("name", "tu producto")
            precio_prod = int(float(prod.get("price", 0)))
        else:
            nombre_prod = "tu producto"
            precio_prod = 0

        telefono_norm = normalize_phone(telefono)

        wa_result = enviar_plantilla_confirmacion(
            telefono_norm, nombre, nombre_prod, f"${precio_prod:,}", f"{direccion}, {comuna}, {region}"
        )

        pending_confirmations[telefono_norm] = order_id

        return {
            "success": True,
            "pedido": {"id": order_id, "nombre": nombre, "telefono": telefono_norm},
            "whatsapp_enviado": wa_result,
            "accion": "Esperando respuesta del cliente: 1=Confirmar, 2=Cancelar, 3=Cambiar dirección"
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/send_whatsapp")
async def send_whatsapp(numero: str = Query(...), mensaje: str = Query(...)):
    result = enviar_whatsapp(numero, mensaje)
    return result

# ---------- WEBHOOK DE WHATSAPP ----------
@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    print(f"Webhook verification: mode={mode}, token={token}, challenge={challenge}")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")

@app.post("/webhook/whatsapp")
async def receive_whatsapp(request: Request):
    body = await request.json()
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        if messages and contacts:
            msg = messages[0]
            contact = contacts[0]
            phone = contact.get("wa_id", "")
            text = msg.get("text", {}).get("body", "")
            print(f"📩 WhatsApp recibido de {phone}: {text}")
            await procesar_respuesta_whatsapp(phone, text)
        return {"status": "received"}
    except Exception as e:
        return {"error": str(e)}

async def procesar_respuesta_whatsapp(phone, text):
    phone_norm = normalize_phone(phone)
    text_clean = text.strip().upper()
    if text_clean in ["1", "SI", "SÍ"]:
        order_id = pending_confirmations.get(phone_norm)
        if order_id:
            timer = threading.Timer(300.0, confirmar_pedido_despues, args=[order_id, phone_norm])
            timer.start()
            enviar_whatsapp(phone_norm, f"✅ Confirmación programada. Tu pedido #{order_id} se confirmará en 5 minutos.")
        else:
            enviar_whatsapp(phone_norm, "No hay un pedido pendiente asociado a este número. Si necesitas ayuda, contáctanos.")
    elif text_clean in ["2", "NO"]:
        enviar_whatsapp(phone_norm, "Pedido cancelado según tu solicitud. Si fue un error, por favor contáctanos.")
    elif text_clean == "3":
        enviar_whatsapp(phone_norm, "Por favor, responde a este mensaje con tu nueva dirección completa (calle, número, comuna, región).")
    else:
        enviar_whatsapp(phone_norm, "No entendí tu respuesta. Responde: 1 para confirmar, 2 para cancelar, 3 para cambiar dirección.")

def confirmar_pedido_despues(order_id, phone):
    try:
        result = client.confirm_order(order_id)
        print(f"✅ Pedido #{order_id} confirmado después de 5 min. Respuesta: {result}")
        enviar_whatsapp(phone, f"¡Gracias! Tu pedido #{order_id} ha sido confirmado. Te avisaremos cuando sea despachado.")
        pending_confirmations.pop(phone, None)
    except Exception as e:
        print(f"❌ Error al confirmar pedido #{order_id}: {str(e)}")

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    print("🚀 Iniciando DropiBot en http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
