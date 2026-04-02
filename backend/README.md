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
pip install -r requirements.txt
```

3. Environment

Copy `.env.example` to `.env` and adjust values if needed.

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Azure OpenAI users can set:

- `AZURE_OPENAI_API_VERSION` (default: `2025-01-01-preview`)

## Run locally

Start the backend from the `backend` folder:

```bash
uvicorn app.main:app --reload --port 8000
```
