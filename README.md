# warrenty-chat

Small FastAPI chat backend and static web client for the Ideatect chat flow.

## Project layout

- `app.py`: FastAPI application
- `web/chat/index.html`: browser chat client
- `systemd/ideatect-chat.service`: systemd unit for the API
- `systemd/README.md`: service-specific restore notes

## Deployment

This app is intended to run on the main `ideatect.com` server behind Apache, without a separate API host.

### 1. Clone the repo

```bash
git clone git@github.com:ext2txe/warrenty-chat.git ideatect
cd ideatect
```

### 2. Create the virtual environment

```bash
python3 -m venv /opt/ideatect/.venv
/opt/ideatect/.venv/bin/pip install fastapi uvicorn gunicorn sqlalchemy pymysql
```

If you deploy to a different directory, adjust the paths below to match.

### 3. Place the app

Expected layout:

```text
/opt/ideatect/
  app.py
  web/
  systemd/
  .venv/
```

### 4. Install the systemd service

```bash
sudo cp /opt/ideatect/systemd/ideatect-chat.service /etc/systemd/system/ideatect-chat.service
sudo systemctl daemon-reload
sudo systemctl enable --now ideatect-chat.service
```

Check status:

```bash
sudo systemctl status ideatect-chat.service
sudo journalctl -u ideatect-chat.service -n 100 --no-pager
```

### 5. Configure Apache

Enable the required modules:

```bash
sudo a2enmod proxy proxy_http headers ssl
sudo systemctl reload apache2
```

Add this inside the SSL vhost for `ideatect.com`:

```apache
ProxyPreserveHost On
RequestHeader set X-Forwarded-Proto "https"

ProxyPass        /chat-api/ http://127.0.0.1:8000/
ProxyPassReverse /chat-api/ http://127.0.0.1:8000/
```

This maps:

- `https://ideatect.com/chat-api/version` -> `http://127.0.0.1:8000/version`
- `https://ideatect.com/chat-api/chat` -> `http://127.0.0.1:8000/chat`

The frontend in `web/chat/index.html` already uses the same-origin `/chat-api` path.

### 6. Configure the database

`app.py` currently uses a hardcoded local MySQL connection:

```text
mysql+pymysql://chatuser:StrongPasswordHere@localhost/ideatect
```

Make sure the following exist on the server:

- MySQL or MariaDB running locally
- database: `ideatect`
- user: `chatuser`
- matching password in `app.py`

### 7. Verify the deployment

Test the API locally on the server:

```bash
curl http://127.0.0.1:8000/version
```

Test through Apache:

```bash
curl https://ideatect.com/chat-api/version
```

## Windows XAMPP deployment

For a local or LAN-only Windows setup with XAMPP:

### 1. Create the Python environment

From the repo root on Windows:

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 2. Run the FastAPI backend locally

Use the helper script:

```powershell
windows\run-backend.bat
```

This starts the API on `http://127.0.0.1:8000`.

### 3. Serve the web client from XAMPP Apache

Two simple options:

- Copy `web\chat\` into `C:\xampp\htdocs\chat\`
- Or use the sample Apache config in `xampp/warrenty-chat-alias.conf`

If you use the sample config, enable Apache proxy modules and include the file from your XAMPP Apache config. The sample maps:

- `/chat` -> the static chat frontend
- `/chat-api/` -> the local FastAPI backend on `127.0.0.1:8000`

### 4. Open the app

If you copied into `htdocs`:

```text
http://localhost/chat/
```

If you used the alias config:

```text
http://localhost/chat
```

The frontend already uses same-origin `/chat-api`, so no frontend code changes are required for XAMPP.

## Notes

- A separate VPS is not required unless you want stronger isolation or separate scaling.
- The service file currently runs as `www-data`; change that in `systemd/ideatect-chat.service` if you prefer a dedicated deploy user.
- Moving the database URL into an environment file would be a sensible next improvement.
