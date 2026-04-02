# AI Business Idea Validator

## Problem

Early-stage founders often validate ideas with scattered notes and vague advice. The hard part is turning an idea into a focused, actionable next step list (market signal, risks, and what to do first).

## Solution

A small web app that takes a business idea and returns a structured analysis:

- Market potential
- Key risks and challenges
- Actionable first steps
- Overall verdict

The UI supports dynamic AI provider selection. Cloud providers are optional and configured by the user; the system can fall back to Ollama locally.

## Core features

- **Single active provider**: choose one of Ollama, OpenAI, Azure OpenAI, Gemini, or Claude.
- **User-supplied models and keys**: model name is typed by the user; cloud keys are entered in the UI.
- **Automatic fallback**: if a cloud provider is misconfigured or fails, the backend falls back to Ollama (when available).
- **Safe output parsing**: the backend extracts JSON and handles imperfect model output without crashing.
- **Simple UI flow**: loading state, clear errors, and structured result sections.

## Architecture

- **Frontend**: React + Vite + Tailwind (`frontend/`)
- **Backend**: FastAPI (`backend/`)
- **AI**: Provider abstraction with Ollama + optional cloud providers (`backend/app/providers.py`)

Key backend modules:

- `backend/app/main.py`: API entrypoint (`POST /analyze-idea`)
- `backend/app/providers.py`: provider clients (Ollama/OpenAI/Azure/Gemini/Claude)
- `backend/app/ai_clients.py`: provider selection + fallback + safe JSON extraction
- `backend/app/prompts.py`: prompt template and required JSON response shape

## Design decisions & tradeoffs

- **Client-side keys**: cloud API keys are entered by the user at runtime. This keeps the demo simple, but it is not ideal for multi-tenant production apps (you would typically store secrets server-side per user).
- **Best-effort JSON repair**: the parser prefers strict JSON but includes extraction/repair to handle small local models that often produce imperfect JSON.
- **Fallback to local**: prioritizes local-first development and avoids hard dependency on any cloud provider.

## Security & configuration

- Do not commit secrets. This repo ships with `.env.example`, not `.env`.
- Backend config is minimal:
  - `OLLAMA_URL` (default: `http://localhost:11434`)
  - `CORS_ORIGINS` (comma-separated allowlist)

See `backend/.env.example`.

## How to run locally

### Prerequisites

- Node.js 18+
- Python 3.10+
- Ollama (optional, for local AI)

### 1) Start Ollama (local)

Install from `https://ollama.com`, then pull a model (example):

```bash
ollama pull qwen2.5:1.5b
```

Run Ollama (if not already running):

```bash
ollama serve
```

### 2) Run the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 3) Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## License

MIT. See `LICENSE`.
