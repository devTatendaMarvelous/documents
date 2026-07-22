# Document & Image Service

Production-ready **FastAPI** file service for documents and images.

Applications (Laravel, Flutter, React, Next.js, and others) communicate with this service over HTTP. It receives files, processes images, serves assets, and deletes them — nothing else.

- **Runtime:** Python 3.13, FastAPI, Gunicorn, Uvicorn workers  
- **Storage:** Local filesystem only (no database, no Docker)  
- **Deploy target:** Ubuntu Linux + Apache 2 reverse proxy + systemd  

---

## Features

| Capability | Details |
|---|---|
| Document upload | PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT, CSV, ZIP |
| Image upload | JPG, JPEG, PNG, WebP |
| Image pipeline | Resize (max 1920px) → compress (q80) → WebP → 300px thumbnail |
| Serving | `/files/`, `/optimized/`, `/thumbnails/` |
| Security | `X-API-Key` on every endpoint except `GET /health` |
| Logging | Structured logs to stdout + `logs/application.log` |

---

## Project layout

```text
documents/
├── app/
│   ├── api/
│   │   ├── upload.py
│   │   ├── files.py
│   │   └── health.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── image_processor.py
│   │   ├── logger.py
│   │   └── constants.py
│   ├── utils/
│   │   └── helpers.py
│   ├── storage/
│   │   ├── documents/
│   │   ├── images/
│   │   ├── optimized/
│   │   └── thumbnails/
│   └── main.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── install.sh
├── documents.service
└── apache-vhost.conf
```

---

## Quick start (development)

```bash
cd documents

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
bash install.sh

# Start with a single Uvicorn worker (dev)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive OpenAPI docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Environment variables

Copy `.env.example` to `.env` (done automatically by `install.sh`):

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `change-me` | Shared secret sent as `X-API-Key` |
| `PORT` | `8000` | Bind port (must match systemd + Apache) |
| `MAX_UPLOAD_SIZE` | `50MB` | Max upload body (`B` / `KB` / `MB` / `GB`) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

**Never commit `.env`.** Rotate `API_KEY` if it leaks.

---

## API documentation

All endpoints except `GET /health` require:

```http
X-API-Key: <your-api-key>
```

Invalid or missing keys return **HTTP 401** with a JSON body.

### Health

```http
GET /health
```

```json
{ "status": "ok" }
```

### Upload document

```http
POST /upload/document
Content-Type: multipart/form-data
```

Field name: `file`

```json
{
  "success": true,
  "filename": "5fbfa1ab-fac8-44d2-b5ba-0d02b51eeb89.pdf",
  "original_name": "invoice.pdf",
  "size": 123456,
  "mime_type": "application/pdf",
  "url": "/files/5fbfa1ab-fac8-44d2-b5ba-0d02b51eeb89.pdf"
}
```

Stored in `app/storage/documents/` with a UUID filename; extension preserved.

### Upload image

```http
POST /upload/image
Content-Type: multipart/form-data
```

Field name: `file`

Pipeline:

1. Save **original** to `storage/images/` (never overwritten later)  
2. Resize if width &gt; 1920px (aspect ratio preserved)  
3. Compress at quality 80  
4. Convert to WebP → `storage/optimized/`  
5. Generate 300px WebP thumbnail → `storage/thumbnails/`  

```json
{
  "success": true,
  "original": "a1b2c3d4-....jpg",
  "optimized": "a1b2c3d4-....webp",
  "thumbnail": "a1b2c3d4-....webp",
  "url": "/files/a1b2c3d4-....jpg",
  "optimized_url": "/optimized/a1b2c3d4-....webp",
  "thumbnail_url": "/thumbnails/a1b2c3d4-....webp"
}
```

### Retrieve file

```http
GET /files/{filename}
```

Serves from `documents/` or `images/` with the correct MIME type.

### Retrieve optimized image

```http
GET /optimized/{filename}
```

### Retrieve thumbnail

```http
GET /thumbnails/{filename}
```

### Delete file

```http
DELETE /files/{filename}
```

Deletes the original **and** matching optimized/thumbnail variants when they exist.

```json
{
  "success": true,
  "message": "Deleted 3 file(s)",
  "deleted": ["a1b2....jpg", "a1b2....webp", "a1b2....webp"]
}
```

### Error responses

All errors are JSON (never HTML):

| Code | Meaning |
|---|---|
| 400 | Bad request / processing failure |
| 401 | Missing or invalid API key |
| 404 | File not found |
| 413 | Upload exceeds `MAX_UPLOAD_SIZE` |
| 415 | Unsupported file type |
| 422 | Validation error (multipart / fields) |
| 500 | Unexpected server error |

---

## curl examples

Set your key once:

```bash
export API_KEY="your-api-key-here"
export BASE="http://127.0.0.1:8000"
```

### Health

```bash
curl -s "$BASE/health"
```

### Upload a document

```bash
curl -s -X POST "$BASE/upload/document" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@./invoice.pdf"
```

### Upload an image

```bash
curl -s -X POST "$BASE/upload/image" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@./photo.jpg"
```

### Download a file

```bash
curl -s -OJ "$BASE/files/<uuid>.pdf" \
  -H "X-API-Key: $API_KEY"
```

### Download optimized / thumbnail

```bash
curl -s -OJ "$BASE/optimized/<uuid>.webp" -H "X-API-Key: $API_KEY"
curl -s -OJ "$BASE/thumbnails/<uuid>.webp" -H "X-API-Key: $API_KEY"
```

### Delete a file

```bash
curl -s -X DELETE "$BASE/files/<uuid>.pdf" \
  -H "X-API-Key: $API_KEY"
```

---

## Ubuntu production deployment

Target layout: `/var/www/documents`

### One-command deploy (recommended)

Copy the project onto the server, then run:

```bash
# From your laptop
scp -r documents/ user@your-server:/tmp/documents

# On the server
ssh user@your-server
sudo bash /tmp/documents/deploy.sh
```

Or if the project is already at `/var/www/documents`:

```bash
cd /var/www/documents
sudo bash deploy.sh
```

Optional overrides:

```bash
sudo SERVER_NAME=files.example.com WORKERS=4 bash deploy.sh
sudo SKIP_APACHE=1 bash deploy.sh          # app only, no VirtualHost
sudo APP_DIR=/opt/documents bash deploy.sh # custom install path
```

`deploy.sh` will:

1. Install Python / Apache packages  
2. Sync the app into `/var/www/documents`  
3. Create the venv and install requirements  
4. Generate `.env` + `API_KEY` if missing  
5. Install and start the `documents` systemd service  
6. Enable an Apache reverse-proxy site  
7. Hit `GET /health` locally  

### Manual steps (if you prefer not to use deploy.sh)

#### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip apache2 \
  libapache2-mod-proxy-html  # optional helpers
sudo a2enmod proxy proxy_http headers rewrite ssl
```

#### 2. Deploy the project

```bash
sudo mkdir -p /var/www/documents
sudo cp -a . /var/www/documents/   # or git clone into place
cd /var/www/documents

sudo python3 -m venv venv
sudo ./venv/bin/pip install --upgrade pip
sudo ./venv/bin/pip install -r requirements.txt
sudo bash install.sh
```

Edit secrets:

```bash
sudo nano /var/www/documents/.env
# Set a strong API_KEY
```

#### 3. Permissions

```bash
sudo chown -R www-data:www-data /var/www/documents
sudo chmod 750 /var/www/documents/app/storage /var/www/documents/logs
sudo chmod 640 /var/www/documents/.env
```

#### 4. systemd

```bash
sudo cp /var/www/documents/documents.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable documents
sudo systemctl start documents
sudo systemctl status documents
```

Useful commands:

```bash
sudo journalctl -u documents -f
sudo systemctl restart documents
```

#### 5. Gunicorn (what systemd runs)

```bash
gunicorn \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  -b 127.0.0.1:8000 \
  --timeout 120 \
  app.main:app
```

| Flag | Purpose |
|---|---|
| `-k uvicorn.workers.UvicornWorker` | ASGI worker class |
| `-w 4` | Worker processes (≈ 2× CPU cores is a common start) |
| `-b 127.0.0.1:8000` | Local bind — Apache proxies publicly |
| `--timeout 120` | Allow large uploads / image processing |

Manual test (as `www-data`):

```bash
cd /var/www/documents
sudo -u www-data ./venv/bin/gunicorn \
  -k uvicorn.workers.UvicornWorker \
  -w 2 \
  -b 127.0.0.1:8000 \
  app.main:app
```

#### 6. Apache reverse proxy

```bash
sudo cp /var/www/documents/apache-vhost.conf \
  /etc/apache2/sites-available/documents.conf
sudo nano /etc/apache2/sites-available/documents.conf
# Change ServerName to your hostname

sudo a2ensite documents
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Minimal VirtualHost:

```apache
<VirtualHost *:80>
    ServerName files.example.com

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    LimitRequestBody 52428800

    ErrorLog ${APACHE_LOG_DIR}/documents_error.log
    CustomLog ${APACHE_LOG_DIR}/documents_access.log combined
</VirtualHost>
```

TLS with Certbot:

```bash
sudo apt install -y certbot python3-certbot-apache
sudo certbot --apache -d files.example.com
```

---

## Virtual environment notes

```bash
cd /var/www/documents
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

The systemd unit uses `/var/www/documents/venv/bin/gunicorn` directly — no need to `source` in production.

---

## API key configuration

1. Put the key in `.env` as `API_KEY=...`  
2. Clients send it on every request:

```http
X-API-Key: <API_KEY value>
```

3. `GET /health` is the only intentionally public endpoint (for load balancers / monitoring).  
4. OpenAPI UI (`/docs`, `/redoc`, `/openapi.json`) also requires `X-API-Key`. Pass the header from your HTTP client, or temporarily allow those paths at the Apache layer for operators.

---

## Logging

- File: `logs/application.log` (rotating, 10 MB × 5 backups)  
- Also printed to **stdout** (captured by journald via systemd)  

Logged events include uploads, downloads, deletes, unauthorized attempts, processing failures, and unexpected exceptions.

```bash
tail -f /var/www/documents/logs/application.log
sudo journalctl -u documents -f
```

---

## Troubleshooting

### Service will not start

```bash
sudo systemctl status documents
sudo journalctl -u documents -n 100 --no-pager
```

Common causes:

- Wrong `WorkingDirectory` in `documents.service`  
- Missing venv or dependencies  
- `.env` missing / unreadable by `www-data`  
- Port 8000 already in use: `sudo ss -tlnp | grep 8000`

### Apache 502 Bad Gateway

- Confirm Gunicorn is listening: `curl -s http://127.0.0.1:8000/health`  
- Confirm proxy modules: `sudo a2enmod proxy proxy_http && sudo systemctl reload apache2`  
- Check Apache error log: `sudo tail -f /var/log/apache2/documents_error.log`

### Permission denied writing storage / logs

```bash
sudo chown -R www-data:www-data /var/www/documents/app/storage /var/www/documents/logs
sudo chmod -R u+rwX /var/www/documents/app/storage /var/www/documents/logs
```

SELinux is uncommon on Ubuntu; if enabled elsewhere, allow the service write access to storage.

### 413 Payload Too Large

- Raise `MAX_UPLOAD_SIZE` in `.env` and restart `documents`  
- Raise Apache `LimitRequestBody` to match  
- If another proxy sits in front, raise its body limit too  

### 401 Unauthorized

- Ensure the client sends `X-API-Key` (exact header name)  
- Confirm the value matches `.env` (`sudo grep API_KEY /var/www/documents/.env`)  
- No `Bearer` prefix — send the raw key  

### Images fail to process

- Confirm Pillow installed in the **venv** used by systemd  
- Check logs for `Image processing failed`  
- Corrupt or non-image payloads disguised with an image extension return HTTP 400  

### Workers dying on large images

- Increase `--timeout` in `documents.service`  
- Reduce `-w` workers if RAM is tight  
- Consider lowering `MAX_IMAGE_WIDTH` in `app/core/constants.py` for constrained hosts  

---

## Production recommendations

1. **Change `API_KEY`** immediately — use a long random value (`openssl rand -hex 32`).  
2. Terminate **TLS** at Apache (or a CDN); keep Gunicorn on `127.0.0.1` only.  
3. Restrict `/docs` and `/redoc` by IP or basic auth on public hosts.  
4. Schedule log rotation is already handled in-app; still monitor disk for `storage/`.  
5. Back up `app/storage/` regularly — this service has no database; files **are** the data.  
6. Tune Gunicorn `-w` to CPU count; start with `2–4` on small VMs.  
7. Set Apache `LimitRequestBody` ≥ `MAX_UPLOAD_SIZE`.  
8. Keep the OS and `venv` packages patched (`pip install -U -r requirements.txt` in a maintenance window).  
9. Do not expose port `8000` on the public interface / firewall.  
10. Use a dedicated hostname (`files.example.com`) and firewall allow-lists for trusted app servers when possible.

---

## Integrating from other apps

Send the API key from your backend (never embed it in public mobile/web clients if the service is internet-facing). Prefer a server-side BFF or signed short-lived URLs behind your main app.

Example (Laravel HTTP client):

```php
$response = Http::withHeaders([
    'X-API-Key' => config('services.files.key'),
])->attach('file', file_get_contents($path), basename($path))
  ->post(config('services.files.url') . '/upload/document');
```

---

## License

Internal / project use — adjust as needed for your organization.
