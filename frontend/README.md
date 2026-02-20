# Business Idea Validator — Frontend

React + Vite + Tailwind UI for the AI Business Idea Validator.

## Setup

```bash
cd frontend
npm install
```

## Run locally

1. **Backend** must be running (e.g. `cd backend && uvicorn app.main:app --reload --port 8000`).
2. Start the dev server (uses Vite proxy so `/api` hits the backend):

   ```bash
   npm run dev
   ```

3. Open **http://localhost:5173**.

## Build

```bash
npm run build
```

Output is in `dist/`. For production, set `VITE_API_URL` to your backend URL (e.g. `https://your-app.onrender.com`) before building.

## Environment

| Variable         | Description |
|------------------|-------------|
| `VITE_API_URL`   | Backend base URL. Leave unset in dev to use the Vite proxy (`/api`). |
