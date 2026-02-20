# Deployment — Render (Backend) + Vercel (Frontend)

Step-by-step deployment for the Business Idea Validator on free-tier-friendly hosting.

---

## Prerequisites

- Code in a **Git repository** (GitHub, GitLab, or Bitbucket).
- **Render** and **Vercel** accounts (free tiers are enough).

---

## 1. Deploy Backend to Render

1. Go to [render.com](https://render.com) and sign in. Create a **New → Web Service**.
2. **Connect** your repo and select the project.
3. **Configure:**
   - **Name:** e.g. `business-idea-validator-api`
   - **Root Directory:** `backend`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. **Environment variables** (Add Environment Variable):
   - `OPENAI_API_KEY` = `sk-...` (required on Render; Ollama won’t run there)
   - Optional: `OPENAI_MODEL` = `gpt-4o-mini`
   - `CORS_ORIGINS` = `https://your-frontend.vercel.app` (add after frontend is deployed; comma-separated for multiple)
5. **Create Web Service**. Note the URL, e.g. `https://business-idea-validator-api.onrender.com`.

### Render notes

- Free tier spins down after inactivity; first request after idle can be slow (cold start).
- Health check: `GET https://your-service.onrender.com/health` should return `{"status":"ok"}`.

---

## 2. Deploy Frontend to Vercel

1. Go to [vercel.com](https://vercel.com) and sign in. **Add New → Project** and import your repo.
2. **Configure:**
   - **Root Directory:** `frontend` (or set to `frontend` in Project Settings).
   - **Framework Preset:** Vite.
   - **Build Command:** `npm run build` (default).
   - **Output Directory:** `dist` (default for Vite).
3. **Environment variables:**
   - `VITE_API_URL` = `https://business-idea-validator-api.onrender.com` (your Render backend URL; no trailing slash).
4. **Deploy**. Note the frontend URL, e.g. `https://your-project.vercel.app`.

---

## 3. CORS

Backend must allow the frontend origin.

1. In **Render** → your Web Service → **Environment**:
   - Set `CORS_ORIGINS` = `https://your-project.vercel.app` (your real Vercel URL).
2. Redeploy the backend if needed.

If you use a custom domain later, add it to `CORS_ORIGINS` (comma-separated).

---

## 4. Build commands summary

| App     | Platform | Root     | Build                          | Start |
|---------|----------|----------|--------------------------------|-------|
| Backend | Render   | `backend`| `pip install -r requirements.txt` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Frontend| Vercel   | `frontend`| `npm run build`                | (static `dist`) |

---

## 5. Switching from Ollama to OpenAI for production

- **Local dev:** Use Ollama (set `OLLAMA_URL`, run Ollama). No API key needed.
- **Production (Render):** Ollama is not available on Render, so the app uses **OpenAI** when `OPENAI_API_KEY` is set.
- **Logic:** Backend tries Ollama first if `OLLAMA_URL` is set and reachable; otherwise it uses OpenAI. On Render, don’t set `OLLAMA_URL` (or set it to `none`), and set `OPENAI_API_KEY`.

No code change required; behavior is driven by environment variables.

---

## 6. Troubleshooting

| Issue | What to do |
|-------|------------|
| Frontend shows "Request failed" / CORS error | Set `CORS_ORIGINS` on Render to your exact Vercel URL (https, no trailing slash). Redeploy backend. |
| Backend returns 503 | Set `OPENAI_API_KEY` on Render. Free tier has no Ollama. |
| Slow first load after idle | Render free tier cold start; first request can take 30–60 s. Consider upgrading or a ping service. |
| 400 on /analyze-idea | Request body must be `{"idea": "..."}` and `idea` non-empty, max 2000 chars. |
| Build fails on Vercel | Ensure root is `frontend`, `npm run build` runs, and `VITE_API_URL` is set if you need it at build time. |

---

## 7. Optional: custom domains

- **Vercel:** Project Settings → Domains → add your domain.
- **Render:** Web Service → Settings → Custom Domain.
- Update `CORS_ORIGINS` to include the new frontend URL and redeploy the backend.
