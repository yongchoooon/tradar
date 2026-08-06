# Cloudflare dashboard input samples

- `r2-cors.dashboard.example.json`: paste into the R2 bucket CORS policy after
  replacing `tradar.example.com` with the actual Pages custom domain.
- Keep only localhost origins that are actually used for development.
- An allowed origin must not include a path and must not end with `/`.
- Never commit a tunnel token, R2 secret key, or Cloudflare API token here.

The named Tunnel is remotely managed in the Cloudflare dashboard. Its published
application maps the public API hostname to the Docker-network service URL
`http://api:8000`. The local token belongs only in `.env.cloudflare` as
`TUNNEL_TOKEN`.
