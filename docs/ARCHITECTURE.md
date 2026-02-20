# AI-Powered Business Idea Validator — System Architecture

## 1. Overview

A simple, production-ready web app: user submits a business idea → backend calls an AI provider → returns structured analysis (market potential, risks, first steps, verdict).

---

## 2. Tech Stack

| Layer        | Choice        | Rationale |
|-------------|----------------|-----------|
| **Frontend** | React + Vite   | Fast, minimal config, great DX. No SSR needed for this app. |
| **Styling**  | Tailwind CSS   | Utility-first, fast to build, small bundle. |
| **Backend**  | FastAPI        | Async, automatic OpenAPI docs, type hints, minimal boilerplate. |
| **AI**       | Ollama (primary) + OpenAI (fallback) | Local-first, no keys for dev; cloud option for production. |
| **Deploy**   | Vercel (frontend) + Render (backend) | Free tiers, simple config, good for startups. |

---

## 3. Folder Structure

```
roasted1/
├── backend/                 # FastAPI app
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # App entry, routes, CORS
│   │   ├── ai_clients.py    # Ollama + OpenAI abstraction
│   │   ├── prompts.py       # Structured prompt templates
│   │   └── schemas.py       # Pydantic request/response models
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
├── frontend/                # React (Vite)
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── index.css
│   │   ├── api.js           # Backend API client
│   │   └── components/
│   │       ├── IdeaForm.jsx
│   │       ├── ResultCard.jsx
│   │       └── LoadingSpinner.jsx
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.js
│   └── README.md
├── docs/
│   ├── ARCHITECTURE.md      # This file
│   ├── OLLAMA_SETUP.md      # Local AI setup
│   ├── DEPLOYMENT.md        # Render + Vercel
│   └── PRODUCT_POLISH.md    # UX, monetization, roadmap
└── README.md                # Project root overview
```

---

## 4. API Design

### Endpoint

- **POST** `/analyze-idea`

### Request

```json
{
  "idea": "A subscription box for indoor plant enthusiasts with care tips and rare seeds"
}
```

### Response (200)

```json
{
  "market_potential": "2–3 paragraphs of analysis…",
  "risks": "Key risks and challenges…",
  "first_steps": "Actionable first steps…",
  "verdict": "Overall verdict and suggestions…"
}
```

### Error Responses

- **400** — Invalid/missing `idea` (e.g. empty string).
- **503** — No AI provider available (Ollama down, OpenAI not configured/failing).

---

## 5. Data Flow

```
[User] → [React Form] → POST /analyze-idea (JSON)
                              ↓
                    [FastAPI] validate body
                              ↓
                    [AI Provider Layer] env: OLLAMA_URL set? → Ollama
                                        else OPENAI_API_KEY set? → OpenAI
                                        else → 503
                              ↓
                    [Prompt] structured template → LLM
                              ↓
                    [Parse] extract 4 sections (or retry/fallback)
                              ↓
                    [Response] JSON → [React] → display in sections
```

---

## 6. AI Provider Switching Logic

- **Priority 1:** If `OLLAMA_URL` is set and reachable → use Ollama.
- **Priority 2:** Else if `OPENAI_API_KEY` is set → use OpenAI.
- **Priority 3:** Else return 503 with a clear message.

Implementation: one interface (e.g. `analyze_idea(idea: str) -> dict`). Two implementations (Ollama client, OpenAI client). A small router in `main.py` or `ai_clients.py` that picks provider from env and health check.

---

## 7. Prompt Engineering Strategy

- **Single structured prompt** asking for exactly 4 sections: Market Potential, Risks, First Steps, Verdict.
- Request **plain text** (no markdown headers if possible) and a fixed delimiter between sections (e.g. `---SECTION---`) so we can parse reliably.
- **Fallback parsing:** if the model returns markdown (e.g. `## Market Potential`), use regex to split by `## SectionName` and map to our keys.
- **Length:** Ask for concise paragraphs (e.g. 2–4 sentences per section) to keep latency and token usage low.
- **System prompt:** Role = “Business idea validator”; tone = constructive, honest, actionable.

---

## 8. Security Basics

- **Input:** Sanitize/validate `idea` (max length e.g. 2000 chars), reject empty.
- **CORS:** Restrict `Allow-Origin` to frontend origin(s) in production; for local dev allow `http://localhost:5173` (Vite).
- **Secrets:** All keys in env vars only; never in code or frontend.
- **Rate limiting:** Optional for production (e.g. slowapi or Render middleware) to avoid abuse.
- **HTTPS:** Enforced by Vercel/Render in production.

---

## 9. Deployment Flow

1. **Backend (Render)**  
   - Connect repo, set root to `backend/` (or use Docker if you add it later).  
   - Set env: `OPENAI_API_KEY` (if not using Ollama on Render).  
   - Build: `pip install -r requirements.txt`  
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

2. **Frontend (Vercel)**  
   - Connect repo, root `frontend/`.  
   - Set env: `VITE_API_URL=https://your-backend.onrender.com`  
   - Build: `npm run build`  
   - Output: `dist`

3. **CORS:** Backend `Allow-Origin` must include the Vercel frontend URL (e.g. `https://your-app.vercel.app`).

4. **Production AI:** On Render you typically use OpenAI (or another cloud LLM); Ollama is for local/dev. Document switching in DEPLOYMENT.md.

---

## 10. Development Blueprint (Step-by-Step)

1. **Backend**
   - Create `backend/` with FastAPI app, `schemas`, `prompts`, `ai_clients` (Ollama + OpenAI), and provider selection from env.
   - Implement POST `/analyze-idea` with validation, error handling, and structured JSON response.
   - Add `requirements.txt` and `.env.example`.

2. **Local AI**
   - Document Ollama install, model pull (e.g. qwen2.5:1.5b, llama3, phi3), and how to run + test the backend against Ollama (see OLLAMA_SETUP.md).

3. **Frontend**
   - Scaffold Vite + React + Tailwind; add form (textarea + submit), loading state, API client, and result sections (market, risks, steps, verdict).
   - Make it responsive and handle errors gracefully.

4. **Deployment**
   - Backend on Render, frontend on Vercel; env vars, build/start commands, CORS; document switching to OpenAI for production (DEPLOYMENT.md).

5. **Polish**
   - UX/UI tweaks, monetization ideas, roadmap, scaling (PRODUCT_POLISH.md).

This keeps the system simple, scalable, and beginner-friendly while remaining production-ready.
