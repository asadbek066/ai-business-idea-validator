# Business Idea Validator — Backend

FastAPI backend for the AI-Powered Business Idea Validator. Uses Ollama (local) by default, with optional OpenAI fallback.

## Setup

1. **Create virtual environment (recommended)**

   ```bash
   cd backend
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Environment**

   Copy `.env.example` to `.env` and adjust if needed. For local dev with Ollama, defaults are fine.

   ```bash
   copy .env.example .env   # Windows
   # cp .env.example .env  # macOS/Linux
   ```

## Run locally

1. Start **Ollama** (see `docs/OLLAMA_SETUP.md`) and pull a model, e.g. `ollama run qwen2.5:1.5b`.
2. From the `backend` folder:

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
