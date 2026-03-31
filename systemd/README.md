# Ideatect chat service restore

This project exposes a FastAPI app from `app.py` and the web client can call it through the main site at `https://ideatect.com/chat-api`.

The checked-in virtualenv metadata shows the original Linux venv was created at:

```text
/opt/ideatect/.venv
```

The included unit file assumes this deployment layout:

```text
/opt/ideatect/
  app.py
  .venv/
```

It also assumes the API is reverse-proxied by Apache from the main site and only needs to listen on:

```text
127.0.0.1:8000
```

## Install

Copy the unit file into systemd:

```bash
sudo cp /opt/ideatect/systemd/ideatect-chat.service /etc/systemd/system/ideatect-chat.service
```

Reload and enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ideatect-chat.service
```

Check status and logs:

```bash
sudo systemctl status ideatect-chat.service
sudo journalctl -u ideatect-chat.service -n 100 --no-pager
```

## Apache reverse proxy

The simplest deployment is to keep the chat API on the same server as `ideatect.com` and proxy `/chat-api/` to the local service.

Enable the required Apache modules:

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

With that in place:

- `https://ideatect.com/chat-api/version` proxies to `http://127.0.0.1:8000/version`
- `https://ideatect.com/chat-api/chat` proxies to `http://127.0.0.1:8000/chat`

If you also serve `www.ideatect.com`, add the same proxy lines to that SSL vhost too.

## Expected runtime dependencies

- Python venv at `/opt/ideatect/.venv`
- `gunicorn`, `uvicorn`, `fastapi`, `sqlalchemy`, and `pymysql` installed in that venv
- local MySQL or MariaDB reachable at `localhost`
- database `ideatect`
- database user `chatuser`

## Notes

- The DB connection string is currently hardcoded in `app.py`.
- If the service should run as a dedicated user instead of `www-data`, update `User=` and `Group=` in the unit file.
- If Apache should proxy to a different local port, update `--bind 127.0.0.1:8000` in the unit file and the `ProxyPass` lines together.
- A separate virtual server is not necessary for this app unless you want stronger isolation or independent scaling. For a small FastAPI service, same-host reverse proxying is the normal, simpler setup.
