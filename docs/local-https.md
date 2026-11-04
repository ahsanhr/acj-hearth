# Local HTTPS hosting

Choose **Caddy or nginx**, not both. Each serves the frontend at
`https://localhost:5173` and forwards `/api/` to FastAPI on `127.0.0.1:8000`.
Start the backend using the [root run guide](../README.md#running-locally).

These certificates are local, not publicly issued. Installing a local CA does
not publish the app online. Keep certificate-authority private keys private.
The configurations below bind to loopback interfaces only.

## Caddy

```sh
brew install caddy
```

Use the repository's `Caddyfile`, updating the frontend path for your checkout:

```caddyfile
{
    auto_https disable_redirects
}

https://localhost:5173 {
    bind 127.0.0.1 ::1
    tls internal
    root * /absolute/path/to/acj-hearth/frontend
    reverse_proxy /api/* 127.0.0.1:8000
    file_server
}
```

The global block disables port-80 redirects, not HTTPS, avoiding macOS privileged
port errors. From the repository root:

```sh
caddy fmt --overwrite ./Caddyfile
caddy run --config ./Caddyfile --adapter caddyfile
```

Allow Caddy to trust its local CA if prompted. If the certificate is not trusted,
leave Caddy running, run `sudo caddy trust` in another terminal, and restart the
browser. Do not run the whole server as root to bypass port-80 errors.

## nginx

Install nginx and generate a trusted local certificate once:

```sh
brew install nginx mkcert
mkcert -install
mkdir -p "$HOME/.config/hearth"
mkcert -cert-file "$HOME/.config/hearth/localhost.pem" \
  -key-file "$HOME/.config/hearth/localhost-key.pem" \
  localhost 127.0.0.1 ::1
```

Find the nginx configuration with `echo "$(brew --prefix)/etc/nginx/nginx.conf"`.
Add this server block **inside the existing `http` block**. Replace `YOUR_USER`
and the frontend path; nginx does not expand `$HOME` or `~` in these directives.

```nginx
server {
    listen 127.0.0.1:5173 ssl;
    listen [::1]:5173 ssl;
    server_name localhost;

    ssl_certificate /Users/YOUR_USER/.config/hearth/localhost.pem;
    ssl_certificate_key /Users/YOUR_USER/.config/hearth/localhost-key.pem;

    root /absolute/path/to/acj-hearth/frontend;
    index index.html;

    location /api/ {
        # No trailing slash: preserve /api/ in forwarded requests.
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

```sh
nginx -t
brew services start nginx
```

For an existing instance, use `nginx -s reload` after configuration changes.
Review other default server blocks if you want nginx to listen only on loopback.

## Troubleshooting

- **502:** check that FastAPI completed startup and listens on port 8000.
- **Origin rejected:** set `AUTH_ALLOWED_ORIGINS=["https://localhost:5173"]` in
  `backend/.env` and restart FastAPI. No trailing slash is allowed.
- **Certificate warning:** trust the CA (`sudo caddy trust` or `mkcert -install`)
  and restart your browser. Do not disable secure cookies.
- **Address already in use:** stop the other process on port 5173 or 8000.

Keep the frontend's `api-base` meta tag set to `/api/v1` for this same-origin
setup. Use **https://localhost:5173** exactly, not HTTP or a different hostname.
