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
- **Safe output parsing**: the backend extracts JSON and handles imperfect model output without crashing.
- **Simple UI flow**: loading state, clear errors, and structured result sections.
- **Configurable Azure API version**: uses `AZURE_OPENAI_API_VERSION` on the backend.

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
- **Best-effort JSON repair**: the parser prefers strict JSON but includes extraction/repair to handle small local models that often produce imperfect JSON.
- **No hidden fallback**: selected provider fails fast with a clear error, which keeps production behavior predictable.

## Security & configuration

- Do not commit secrets. This repo ships with `.env.example`, not `.env`.
- Backend config is minimal:
  - `CORS_ORIGINS` (comma-separated allowlist)
  - `AZURE_OPENAI_API_VERSION` (default: `2025-01-01-preview`)

See `backend/.env.example`.

## Quick test (deployed app)

1. Open the frontend link above.
2. Go to **Settings** and choose one provider.
3. Enter model/deployment name + API key (and endpoint for Azure OpenAI).
4. Click **Test API Key**.
5. Save settings and submit a sample idea.

## How to run locally

### Prerequisites

- Node.js 18+
- Python 3.10+

### 1) Run the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2) Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## License

MIT. See `LICENSE`.
