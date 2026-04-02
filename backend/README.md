# Business Idea Validator - Backend

FastAPI backend for the AI Business Idea Validator. Uses Ollama (local) by default, with optional cloud providers.

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
pip install -r requirements.txt
```

3. Environment

Copy `.env.example` to `.env` and adjust values if needed.

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

## Run locally

1. Start Ollama and pull a model, for example:

```bash
ollama run qwen2.5:1.5b
```

2. Start the backend from the `backend` folder:

```bash
uvicorn app.main:app --reload --port 8000
```
