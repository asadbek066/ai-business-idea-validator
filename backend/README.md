# Business Idea Validator - Backend

FastAPI backend for the AI Business Idea Validator using cloud providers (OpenAI, Azure OpenAI, Gemini, Claude).

## Setup

1. Create virtual environment (recommended)

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

2. Install dependencies

```bash
pip install --require-hashes -r requirements-dev.lock
```

3. Environment

Copy `.env.example` to `.env` and adjust values if needed.

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Azure OpenAI users can set:

- `AZURE_OPENAI_API_VERSION` (default: `2025-01-01-preview`)
- `CORS_ORIGINS` as a comma-separated explicit frontend-origin allowlist
- `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW_SECONDS`,
  `ANALYZE_RATE_LIMIT`, and `VALIDATE_PROVIDER_RATE_LIMIT`
- `MAX_REQUEST_BODY_BYTES` (default 64 KiB), `PROVIDER_CONCURRENCY_LIMIT`,
  `PROVIDER_QUEUE_TIMEOUT_SECONDS`, `PROVIDER_REQUEST_TIMEOUT_SECONDS`,
  `ANALYZE_DEADLINE_SECONDS`, and `VALIDATE_DEADLINE_SECONDS`
- `PER_CLIENT_CONCURRENCY_LIMIT` (default 2): in-flight provider calls one
  client address may hold; extra requests get `429` with `Retry-After` and do
  not use a global slot

The API accepts one explicitly enabled provider per request. Azure endpoints
must use HTTPS and an Azure OpenAI resource hostname. The backend resolves the
host before sending a key and rejects non-global addresses. Keys are accepted
only for the selected request and are never persisted by this application. The
backend rejects malformed provider output instead of returning a successful
but incomplete analysis.

## Run locally

Start the backend from the `backend` folder:

```bash
uvicorn app.main:app --reload --port 8000 --env-file .env
```

`GET /health` is a lightweight liveness check. `POST /analyze-idea` and
`POST /validate-provider` are intentionally unauthenticated BYOK endpoints;
the built-in limiter and provider capacity gate are process-local, so a
multi-instance deployment should also enforce request and egress limits at its
gateway. Provider calls use the deployment-based Azure Chat Completions path
and the configured `AZURE_OPENAI_API_VERSION`; update that setting deliberately
when adopting a newer Azure API contract.

### Client address behind a proxy

Rate limits (and per-client concurrency) are keyed on a client address. By
default that is the socket peer, which is correct when the API is reached
directly. Behind a reverse proxy or a platform edge (for example Vercel) every
user would otherwise share the proxy's address and one bucket, so configure how
the address is derived. `X-Forwarded-For` is client-controlled and is never
trusted unless you opt in:

- `TRUSTED_PROXY_COUNT` (default `0` = off): number of proxies you operate in
  front of the app. The Nth-from-last `X-Forwarded-For` entry is used, so
  entries a client prepends are ignored. Use `1` for a single proxy that
  appends the peer address it saw.
- `CLIENT_IP_HEADER` (default empty): name of a single-value header your
  platform overwrites on every request, such as `x-real-ip`. Takes precedence
  over `TRUSTED_PROXY_COUNT`. A header that is absent or repeated is ignored.

Values that are not valid IPv4/IPv6 literals fall back to the socket peer.
IPv6 clients are keyed on their /64 and IPv4-mapped IPv6 maps to IPv4. Only
set these when every request really passes through the proxy; otherwise
callers can spoof the header. The repository does not record where the backend
is hosted. On Vercel, platform documentation states the edge overwrites
`X-Forwarded-For` and sets `X-Real-IP`, so `CLIENT_IP_HEADER=x-real-ip` is the
expected choice; this was not verified against a live deployment.

Client disconnects cancel the in-flight bounded task when the server observes
them. A request that was already accepted by a provider cannot be recalled, so
provider quotas and gateway egress policy remain part of production operations.

For a runtime-only install use `requirements.lock`; `requirements-dev.lock`
adds pytest, coverage, Ruff, mypy, Bandit, and pip-audit for local/CI checks.
