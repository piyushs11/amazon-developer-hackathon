# infra

**Owner:** Dev 3 (Dev 1 for data stores)

One EC2 instance running Docker Compose: Caddy (HTTPS) → app (API + MCP gateway) → Postgres,
plus the mock services for the demo.

| File | What |
|---|---|
| `Dockerfile` | One image for API + gateway (`docker build -f infra/Dockerfile .`) |
| `Caddyfile` | `https://$DOMAIN` → `app:8000`; `/mock-oauth/*` → fake OAuth |
| `deploy.sh` | SSH → `git pull` → `docker compose --profile ec2 up -d --build` → health check |

## Run the app in Docker locally
```bash
docker compose --profile app up -d --build     # postgres, demo-api, oauth, app
curl localhost:8000/health
```

## EC2 setup (one time, by hand)
1. **Instance:** Ubuntu 24.04, `t3.small`, 20 GB disk. IAM instance role with S3 and
   Secrets Manager read/write on our prefix only (for `MODE=aws` later).
2. **Network:** allocate an Elastic IP and attach it. Security group: 80 and 443 from anywhere,
   22 from your IP only.
3. **DNS:** an `A` record for `<domain>` pointing at the Elastic IP.
4. **Docker:** `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker ubuntu`
   (log out and in again).
5. **Code + config:**
   ```bash
   git clone <repo> mcp-bridge && cd mcp-bridge
   cp .env.example .env
   ```
   In `.env`, set `DOMAIN`, `GATEWAY_URL=https://<domain>`, `API_URL=https://<domain>`,
   `FRONTEND_URL`, and **new random values** for `PLATFORM_JWT_SECRET`, `OAUTH_STATE_SECRET`
   and `TOKEN_ENC_KEY` (`openssl rand -hex 32`). For the fake OAuth page in the browser:
   `AUTHORIZE_REWRITES=http://localhost:9100=https://<domain>/mock-oauth`.
6. **Start:** `docker compose --profile ec2 up -d --build`
7. **Check from your laptop:**
   ```bash
   curl https://<domain>/health
   curl -X POST https://<domain>/mcp/11111111-1111-1111-1111-111111111111 \
     -H "Authorization: Bearer $DEMO_USER_TOKEN" -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```

Afterwards, deploy from your machine: `EC2_HOST=ubuntu@<ip> DOMAIN=<domain> infra/deploy.sh`.

## Backups
Daily `pg_dump` to S3 (crontab on the instance; the bucket comes from Dev 1):
```
0 4 * * * cd ~/mcp-bridge && docker compose exec -T postgres pg_dump -U mcpbridge mcpbridge | gzip | aws s3 cp - s3://<bucket>/backups/$(date +\%F).sql.gz
```

## Scale path (pitch, not build)
Same image on several instances behind an Application Load Balancer, or on ECS Fargate.
That works because the gateway keeps no local state (the bundle cache is rebuilt from storage).
