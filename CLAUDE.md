# AI Business Idea Validator

A small web app that takes a business idea and returns a structured analysis (market potential, key risks, first steps and an overall verdict) from one user-selected cloud AI provider. It has a React 18 + Vite + Tailwind frontend in `frontend/` and a FastAPI backend in `backend/`. Users enter their own model name and API key at runtime (BYOK). The backend has no server-side key fallback, and a provider failure returns an error instead of a fabricated verdict.

## Commands

CI runs two jobs (`.github/workflows/ci.yml`). Backend runs on Python 3.10 to 3.13 from `backend/`:

```sh
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements-dev.lock
python -m pip check
python -m pip_audit -r requirements-dev.lock
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=75
ruff check app tests ../scripts
ruff format --check app tests ../scripts
mypy app
python -m compileall -q app tests ../scripts
python ../scripts/secret_scan.py
```

Frontend runs on Node 24 from `frontend/`:

```sh
npm ci --ignore-scripts
# dependency audit: run the audit step exactly as written in .github/workflows/ci.yml
npm audit signatures
npm run lint                  # eslint . --max-warnings=0
npm test                      # vitest run
npm run build                 # vite build
git diff --check
```

After the build, CI fails if `git status --porcelain -uall` shows any change or untracked file. `engines.node` is `>=22.13.0`.

Local run: `pip install --require-hashes -r requirements-dev.lock` in `backend/`, then `uvicorn app.main:app --reload --port 8000 --env-file .env`. In `frontend/`, run `npm ci` and `npm run dev`, which serves on port 5173.

## Layout

- `backend/app/main.py`: FastAPI entry point, `POST /analyze-idea`, plus the rate-limited provider validation route.
- `backend/app/providers.py`: OpenAI, Azure OpenAI, Gemini and Claude HTTP clients, with response-size, retry and deadline limits.
- `backend/app/ai_clients.py`: provider selection and safe JSON extraction.
- `backend/app/prompts.py`: system prompt and the required JSON response shape.
- `backend/tests/`: pytest suite, measured for coverage over `app`.
- `backend/requirements.txt` and `requirements-dev.txt`: direct dependencies. The `.lock` files next to them are hash-pinned and generated with `uv pip compile`.
- `backend/.env.example`: backend configuration template.
- `frontend/`: React app. `package.json` holds the scripts and `eslint.config.js` the lint rules.
- `scripts/secret_scan.py`: fails when tracked files contain OpenAI-style, Google, GitHub or Slack tokens, or private keys. CI runs it.

## Rules for changes

- Regenerate the locks after dependency edits with the command in each lock file's header (for example `uv pip compile backend/requirements-dev.txt --universal --python-version 3.10 --generate-hashes -o backend/requirements-dev.lock`). CI installs with `--require-hashes`, so every entry needs hashes.
- Backend config names are `CORS_ORIGINS`, `AZURE_OPENAI_API_VERSION`, `LOG_LEVEL`, `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW_SECONDS`, `ANALYZE_RATE_LIMIT`, `VALIDATE_PROVIDER_RATE_LIMIT`, `MAX_REQUEST_BODY_BYTES`, `PROVIDER_CONCURRENCY_LIMIT`, `PROVIDER_QUEUE_TIMEOUT_SECONDS`, `PROVIDER_REQUEST_TIMEOUT_SECONDS`, `ANALYZE_DEADLINE_SECONDS` and `VALIDATE_DEADLINE_SECONDS`. Keep `backend/.env.example` in sync.
- Do not persist API keys. The frontend keeps them in memory for the tab session, and persisted settings store blank key fields.
- User idea text is delimited and escaped before it reaches prompts. Gemini and Claude receive instructions in their native system fields. Keep both when editing `prompts.py` or `providers.py`.
- Azure endpoints must be HTTPS Azure OpenAI resource hosts from the allowlist, and resolved addresses must be globally routable. Provider errors must not include request URLs or credentials.
- Model output is rejected when incomplete, non-string or oversized. Do not add a fallback that returns a verdict when a provider fails.
- Rate limits are process-local. Do not describe them as shared across instances.
- Keep each `backend/` change within the lint, format and mypy checks above. CI runs `ruff` and `mypy` over `app`, and `ruff` over `tests` and `../scripts`.
