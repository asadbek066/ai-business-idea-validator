# AI Business Idea Validator

## Live

- Demo: https://ai-business-idea-validator-frontend.vercel.app

## Problem

Early-stage founders often validate ideas with scattered notes and vague advice. The hard part is turning an idea into a focused, actionable next step list (market signal, risks, and what to do first).

## Solution

A small web app that takes a business idea and returns a structured analysis:

- Market potential
- Key risks and challenges
- Actionable first steps
- Overall verdict

The UI supports dynamic cloud provider selection. Providers are configured by the user.

## Core features

- **Single active provider**: choose one of OpenAI, Azure OpenAI, Gemini, or Claude.
- **User-supplied models and keys**: model name is typed by the user; cloud keys are entered in the UI.
- **Fail-closed output parsing**: the backend accepts only complete, bounded structured results; provider failures never become a fake verdict.
- **Simple UI flow**: loading state, clear errors, and structured result sections.
- **Configurable Azure API version**: uses `AZURE_OPENAI_API_VERSION` on the backend.
- **Bounded public API**: request-size and process-local rate limits protect the
  unauthenticated analysis endpoints from accidental or abusive overload.
- **Bounded provider work**: shared HTTP pools, in-flight capacity, total
  deadlines, and provider response limits prevent one caller from consuming
  unbounded worker resources.

## Architecture

- **Frontend**: React + Vite + Tailwind (`frontend/`)
- **Backend**: FastAPI (`backend/`)
- **AI**: Provider abstraction for cloud providers (`backend/app/providers.py`)

Key backend modules:

- `backend/app/main.py`: API entrypoint (`POST /analyze-idea`)
- `backend/app/providers.py`: provider clients (OpenAI/Azure/Gemini/Claude)
- `backend/app/ai_clients.py`: provider selection + safe JSON extraction
- `backend/app/prompts.py`: prompt template and required JSON response shape

## Design decisions & tradeoffs

- **BYOK workflow**: cloud API keys are entered by the user at runtime.
- **No key persistence in localStorage**: keys stay in memory for the current tab session.
- **Tolerant extraction, strict contract**: fenced or embedded JSON and the
  documented section format are accepted, but incomplete, non-string, and
  oversized model output is rejected.
- **No hidden fallback**: selected provider fails fast with a clear error, which keeps production behavior predictable.
- **Provider boundary checks**: Azure endpoints must be HTTPS Azure OpenAI
  resource hosts; provider responses and errors are bounded and public errors
  never include request URLs or credentials.
- **Untrusted idea text**: user content is delimited/escaped before it reaches
  provider prompts, and Gemini/Claude use native system-instruction fields.
- **Fail-safe egress**: Azure resource hosts are allowlisted and resolved
  addresses must be globally routable; production deployments should still
  enforce outbound egress policy.

## Security & configuration

- Do not commit secrets. This repo ships with `.env.example`, not `.env`.
- Backend config is minimal:
  - `CORS_ORIGINS` (comma-separated allowlist)
  - `AZURE_OPENAI_API_VERSION` (default: `2025-01-01-preview`)
  - `RATE_LIMIT_*` settings for the process-local abuse guard
  - `MAX_REQUEST_BODY_BYTES`, `PROVIDER_CONCURRENCY_LIMIT`,
    `PROVIDER_QUEUE_TIMEOUT_SECONDS`, and provider deadline settings
- The backend expects an explicit `ai_providers` object with exactly one
  enabled provider. It does not have a server-side API-key fallback.
- API keys are held in memory for the current tab/request only. Persisted
  browser settings contain blank key fields, and disabled provider keys are not
  sent to the backend.
- The process-local limiter is not a substitute for a shared gateway limiter
  when running multiple public instances.
- A browser disconnect cancels the server-side task when observed. A provider
  may already have accepted a request before cancellation, so deployment-level
  quotas and provider billing controls remain important.

See `backend/.env.example`.

## Quick test (deployed app)

1. Open the frontend link above.
2. Go to **Settings** and choose one provider.
3. Enter model/deployment name + API key (and endpoint for Azure OpenAI).
4. Click **Test API Key**.
5. Save settings and submit a sample idea.

## How to run locally

### Prerequisites

- Node.js 22.13+ (Node 24 is used in CI)
- Python 3.10+

### 1) Run the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install --require-hashes -r requirements-dev.lock
copy .env.example .env
uvicorn app.main:app --reload --port 8000 --env-file .env
```

### 2) Run the frontend

```bash
cd frontend
npm ci
npm test
npm run lint
npm run dev
```

Open `http://localhost:5173`.

## License

MIT. See `LICENSE`.
