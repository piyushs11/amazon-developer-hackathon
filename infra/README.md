# infra

**Owner:** Dev 3 (Dev 1 for data stores)

One EC2 instance running Docker Compose: Caddy (HTTPS) → app (API + MCP gateway) → Postgres,
plus the mock services for the demo.

| File | What |
|---|---|
| `Dockerfile` | One image for API + gateway (`docker build -f infra/Dockerfile .`) |
| `Caddyfile` | `https://$DOMAIN` → `app:8000`; `/mock-oauth/*` → fake OAuth |
| `deploy.sh` | SSH → `git pull` → `docker compose --profile ec2 up -d --build` → health check |

Every `up` also runs the one-shot `seed` service (after Postgres and the mock `catalog` are
healthy): it loads the catalog's services into the registry. It is safe to re-run and never
touches a published bundle. Check it with `docker compose logs seed`
(expect `seeded 1111...: Demo Bistro (3 endpoints)`). Locally: `make seed`.

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
7. **Check from your laptop:** (routes: `backend/app/api/README.md`)
   ```bash
   curl https://<domain>/health
   # connect + publish as a demo user:
   TOKEN=$(curl -s -X POST https://<domain>/auth/demo-login -H 'Content-Type: application/json' \
     -d '{"username":"alice"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["user_token"])')
   curl -s -H "Authorization: Bearer $TOKEN" \
     "https://<domain>/oauth/start?service_uuid=11111111-1111-1111-1111-111111111111"
   # open the returned auth_url in a browser, sign in; then:
   JOB=$(curl -s -X POST https://<domain>/publish -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"service_uuid":"11111111-1111-1111-1111-111111111111"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
   curl -s -H "Authorization: Bearer $TOKEN" https://<domain>/publish/$JOB   # repeat until done
   curl -X POST https://<domain>/mcp/11111111-1111-1111-1111-111111111111 \
     -H "Authorization: Bearer $DEMO_USER_TOKEN" -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```

Afterwards, deploy from your machine: `EC2_HOST=ubuntu@<ip> DOMAIN=<domain> infra/deploy.sh`.

## AWS setup for publishing (Bedrock, S3, Secrets Manager, SES)
Publishing runs a Bedrock test of every generated tool, stores the bundle in S3, reads the
service's dev token, and emails a report if a tool cannot be onboarded. In `.env` set
`MODE=aws`, `S3_BUCKET`, `ERROR_S3_BUCKET`, `AWS_REGION` (a US region), `ALERT_FROM_EMAIL`,
`AMAZON_SUPPORT_EMAIL`, and the three random secrets from step 5.

1. **Dev token.** Either create the secret `demo_bistro_dev` with value `{"token":"demo-token"}`,
   or set `DEMO_BISTRO_DEV_TOKEN=demo-token` in `.env` (used when the secret is missing or
   unreadable). `demo-token` is what the demo API accepts.
2. **Bedrock.** In the Bedrock console, enable model access for the model in `BEDROCK_MODEL_ID`
   (Claude Haiku 4.5) in the same region.
3. **SES.** Verify the `ALERT_FROM_EMAIL` address (and `AMAZON_SUPPORT_EMAIL` while the account
   is in the SES sandbox).
4. **Instance role policy** (replace the placeholders):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:Converse"],
        "Resource": "*"},
       {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
        "Resource": ["arn:aws:s3:::<S3_BUCKET>", "arn:aws:s3:::<S3_BUCKET>/*",
                     "arn:aws:s3:::<ERROR_S3_BUCKET>", "arn:aws:s3:::<ERROR_S3_BUCKET>/*"]},
       {"Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"],
        "Resource": "arn:aws:secretsmanager:<region>:<account>:secret:*_dev-*"},
       {"Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue",
                   "secretsmanager:CreateSecret", "secretsmanager:DeleteSecret"],
        "Resource": "arn:aws:secretsmanager:<region>:<account>:secret:mcp-bridge/*"},
       {"Effect": "Allow", "Action": ["ses:SendRawEmail"], "Resource": "*"}
     ]
   }
   ```
5. **Let containers use the instance role.** Docker adds a network hop, so raise the metadata
   hop limit from 1 to 2 (otherwise boto3 in the container finds no credentials):
   ```bash
   aws ec2 modify-instance-metadata-options --instance-id <id> \
     --http-put-response-hop-limit 2 --http-endpoint enabled
   ```
6. **Check from the instance:**
   `docker compose exec app python -c "import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"`
   should print the instance role's ARN.

**User tokens (`TOKEN_PROVIDER=secrets`, the Docker/EC2 default).** When a user connects a
service, their token is stored as one secret per user and service, named
`mcp-bridge/<service_uuid>/<user_id>` (JSON with `token`, `refresh_token`, `expires_at`). The
policy statement on `mcp-bridge/*` above lets the instance create, update, read and delete only
those secrets (a deleted secret is removed immediately so the user can reconnect). Each secret
costs about $0.40 per month, and reads are cached in the app for 30 seconds.

If AWS cannot be reached (no credentials, no network, access denied, throttled) the app logs
`AWS Secrets Manager unavailable ...` and uses the encrypted Postgres store instead, retrying
AWS after 60 seconds. Tokens saved in Postgres during an outage are still found afterwards, and
the next refresh moves them to Secrets Manager. To skip AWS completely (e.g. a laptop), set
`TOKEN_PROVIDER: local` on the `app` service in `docker-compose.yml`. The Postgres store needs
`TOKEN_ENC_KEY` to stay the same: a new key makes old Postgres-stored tokens unreadable.

The `businesses` table (name, service names and email of each service's owner) is created by the
seed step. Rows for the catalog's services come from
`backend/app/db/registry/businesses_seed.json` (an existing row is never overwritten), and
publishing creates a placeholder row (no email) for any service that has none. Failure reports go
to the stored business email, always copied to `AMAZON_SUPPORT_EMAIL`; without a stored email
they go to `AMAZON_SUPPORT_EMAIL` only. Edit the seed file's email before deploying (or update
the row: `docker compose exec postgres psql -U mcpbridge -c "UPDATE businesses SET email='...' WHERE service_uuid='...'"`).

## Backups
Daily `pg_dump` to S3 (crontab on the instance; the bucket comes from Dev 1):
```
0 4 * * * cd ~/mcp-bridge && docker compose exec -T postgres pg_dump -U mcpbridge mcpbridge | gzip | aws s3 cp - s3://<bucket>/backups/$(date +\%F).sql.gz
```

## Scale path (pitch, not build)
Same image on several instances behind an Application Load Balancer, or on ECS Fargate.
That works because the gateway keeps no local state (the bundle cache is rebuilt from storage).
