# Deploying LinBot to Railway

**Production URL:** https://agent.alexlinyx.com — a Railway custom domain
(CNAME `agent` → `fyuuuaao.up.railway.app` plus a `_railway-verify.agent` TXT
record, both DNS-only in Cloudflare; Railway issues and renews the TLS
certificate). The default `lin-bot-production.up.railway.app` URL remains as
an alias of the same service.

The service runs as one always-on container plus a managed Postgres database.
At ~10 concurrent users the async server is nowhere near its limits; the reason
for a *paid, always-on* instance is the "always up" requirement — free tiers
sleep when idle and cold-start in the student's face.

**Why Railway:** simplest managed-Postgres story and auto-deploy from GitHub.
Render or Fly.io are drop-in equivalents; nothing in the repo is Railway-specific
(the app is a container that reads `DATABASE_URL` and `PORT` — the same shape
every PaaS provides).

## One-time setup

1. **Push the repo to GitHub** (Railway deploys from a GitHub repo).
2. **Create a Railway project** at railway.app → *New Project* → *Deploy from
   GitHub repo* → pick this repo. Railway detects the `Dockerfile` and builds it.
3. **Add Postgres**: in the project, *New* → *Database* → *PostgreSQL*.
4. **Wire the database to the app**: in the app service → *Variables*, add
   `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (a Railway reference variable —
   the app normalizes Railway's `postgres://` scheme automatically).
5. **Set the remaining variables** in the app service (see `.env.example`):
   - `PROVIDER=deepseek`
   - `DEEPSEEK_API_KEY=...` (from platform.deepseek.com — this is the one real secret)
   - `MODEL_NAME=deepseek-chat`
   - `RATE_LIMIT=30`
   The app validates config at boot and the deploy will fail loudly if something
   required is missing — that's by design.
6. **Confirm it's always-on**: Railway's default service (no serverless/sleep
   option enabled) stays running. Do not enable "App Sleeping".

Migrations run automatically: the container's start command is
`alembic upgrade head && uvicorn ...`, so the schema always matches the code.

## Verify a deploy

```sh
curl https://<your-app>.up.railway.app/healthz
curl -X POST https://<your-app>.up.railway.app/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "How does a hash map achieve O(1) lookup?"}'
```

Then check a row landed in Postgres (Railway → Postgres → *Data*, or `psql`):
`select question, model_id, provider, created_at from requests order by created_at desc limit 5;`

## Ongoing

- Every push to `main` auto-deploys (CI runs lint + tests on GitHub first;
  optionally enable "wait for CI" in Railway settings so red builds don't ship).
- Phase 2 rollout is config, not code: set `HF_ENDPOINT_URL`, `HF_TOKEN`,
  `CANARY_PROVIDER=hf`, `FALLBACK_PROVIDER=deepseek`, then raise
  `CANARY_PERCENT` from 0 as confidence grows. Rollback = set it back to 0.
