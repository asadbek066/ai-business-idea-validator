# Business Idea Validator — Frontend

React + Vite + Tailwind UI for the AI Business Idea Validator.

## Setup

```bash
cd frontend
npm ci
```

Copy `.env.example` when a direct backend URL is needed; leave
`VITE_API_URL` empty when using the Vite development proxy.

## Run locally

1. **Backend** must be running (e.g. `cd backend && uvicorn app.main:app --reload --port 8000 --env-file .env`).
2. Start the dev server (uses Vite proxy so `/api` hits the backend):

   ```bash
   npm run dev
   ```

3. Open **http://localhost:5173**.

## Build

```bash
npm run build
npm test
npm run lint
```

Output is in `dist/`. For production, set `VITE_API_URL` to an HTTPS backend
URL (e.g. `https://your-app.onrender.com`) before building. The client sends
only the currently selected provider configuration; disabled provider keys are
not posted. Persisted settings never contain API-key values; keys remain in
the current tab's memory.

The Vite 8 toolchain requires Node 22.12+ (or Node 20.19+), and the current
ESLint toolchain requires Node 22.13+ on the Node 22 line. The project
declares Node 22.13+ as its supported floor and uses Node 24 in CI.

## Environment

| Variable         | Description |
|------------------|-------------|
| `VITE_API_URL`   | Backend base URL. Leave unset in dev to use the Vite proxy (`/api`). |
