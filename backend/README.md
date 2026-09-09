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
pip install -r requirements-dev.txt
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

The API accepts one explicitly enabled provider per request. Azure endpoints
must use HTTPS and an Azure OpenAI resource hostname. Keys are accepted only
for the selected request and are never persisted by this application.

## Run locally

Start the backend from the `backend` folder:

```bash
uvicorn app.main:app --reload --port 8000
```

`GET /health` is a lightweight liveness check. `POST /analyze-idea` and
`POST /validate-provider` are intentionally unauthenticated BYOK endpoints;
the built-in limiter is process-local, so a multi-instance deployment should
also enforce limits at its gateway.
