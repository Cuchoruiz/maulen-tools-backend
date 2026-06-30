const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const http = require('http');

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

client.on('qr', qr => {
    console.log('🔍 Escanea este código QR con WhatsApp:');
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    console.log('✅ WhatsApp conectado y listo para enviar mensajes.');
});

// ---------- NORMALIZAR NÚMEROS ----------
function normalizePhone(input) {
    // Quitar @c.us, @lid, @g.us, espacios, +
    let clean = input.replace(/@c\.us|@lid|@g\.us|\s|\+/g, '');
    // Si ya empieza con 56, lo dejamos; si no, le ponemos 56
    if (clean.startsWith('56')) return clean;
    return '56' + clean;
}

// ---------- ESCUCHAR MENSAJES ----------
client.on('message', async msg => {
    const body = msg.body.trim().toUpperCase();
    if (body === 'SI' || body === 'NO') {
        // Usar msg.author si existe (respuesta en grupo/lista), si no msg.from
        const rawNumber = msg.author || msg.from;
        const phone = normalizePhone(rawNumber);
        console.log(`📩 Respuesta recibida de ${rawNumber} (normalizado: ${phone}): "${body}"`);

        const options = {
            hostname: 'localhost',
            port: 8000,
            path: `/confirm_response?phone=${encodeURIComponent(phone)}&response=${body}`,
            method: 'GET'
        };
        const req = http.request(options, res => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                console.log('Respuesta del backend:', data);
            });
        });
        req.on('error', e => console.error('Error al contactar al backend:', e.message));
        req.end();
    }
});

// ---------- SERVIDOR HTTP PARA ENVIAR MENSAJES ----------
const server = http.createServer((req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
    }

    if (req.method === 'POST' && req.url === '/send') {
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', async () => {
            try {
                const { number, message } = JSON.parse(body);
                const finalNumber = normalizePhone(number);
                await client.sendMessage(`${finalNumber}@c.us`, message);
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ success: true, message: 'Mensaje enviado' }));
            } catch (err) {
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ success: false, message: err.message }));
            }
        });
        return;
    }

    res.writeHead(404);
    res.end('Not Found');
});

server.listen(4000, () => {
    console.log('🚀 Servidor de WhatsApp listo en http://localhost:4000');
});

client.initialize();