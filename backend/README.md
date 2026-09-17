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

Client disconnects cancel the in-flight bounded task when the server observes
them. A request that was already accepted by a provider cannot be recalled, so
provider quotas and gateway egress policy remain part of production operations.

For a runtime-only install use `requirements.lock`; `requirements-dev.lock`
adds pytest, coverage, Ruff, mypy, Bandit, and pip-audit for local/CI checks.
