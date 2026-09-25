# Engineering Campaign State

Updated: 2026-09-25

## Purpose and architecture

AI Business Idea Validator is a React/Vite frontend backed by a FastAPI service. Users submit an idea and choose one BYOK cloud provider (OpenAI, Azure OpenAI, Gemini, or Claude). The backend has no database or server-side provider key store. It bounds request size, rate, provider concurrency, deadlines, and response sizes, and returns only complete structured analyses.

Request flow: `frontend/src/App.jsx` calls `frontend/src/api.js`; the API sends the selected provider configuration to `POST /analyze-idea` or `POST /validate-provider`. Backend routing lives in `backend/app/main.py`; request schemas and Azure endpoint validation are in `backend/app/schemas.py`; provider transport is in `backend/app/providers.py`; provider selection and output parsing are in `backend/app/ai_clients.py`. Local frontend requests use the Vite proxy. README identifies a Vercel frontend, but this checkout does not define the production backend deployment target.

## Instructions and verified commands

- No `AGENTS.md` was found in the repository or its parent directories.
- CI is defined in `.github/workflows/ci.yml`. Python matrix is 3.10–3.13; frontend CI uses Node 24.
- Backend install: `python -m pip install --require-hashes -r requirements-dev.lock` from `backend/`.
- Backend checks: `python -m pip check`; `python -m pip_audit -r requirements-dev.lock`; `python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=75`; `ruff check app tests ../scripts`; `ruff format --check app tests ../scripts`; `mypy app`; `python -m compileall -q app tests ../scripts`; `python ../scripts/secret_scan.py`.
- Frontend install/checks: `npm ci --ignore-scripts`, `npm audit --audit-level=high`, `npm audit signatures`, `npm run lint`, `npm test`, and `npm run build` from `frontend/`.

## Baseline

Executed 2026-09-25 on Python 3.12.3 and Node 26.10.0 (the latter differs from CI's Node 24):

- Backend: 71 tests passed; total coverage 78.17% (CI floor 75%); pip check, pip-audit, Ruff lint/format, mypy, compileall, and secret scan all passed.
- Frontend: 11 tests passed; npm audit found 0 vulnerabilities; all 220 installed package signatures verified; lint and production build passed.
- GitHub Actions main run `35212863696` on HEAD `486ec270995b` completed successfully on 2026-09-17.
- `git diff --check` passed. Initial tracked tree was clean.
- Full CI matrix was not rerun locally; CI evidence above covers it at current main.

## Post-fix validation

- Backend suite: 72 tests passed; coverage 78.44% (CI floor 75%). pip check, pip-audit, Ruff lint/format, mypy, compileall, tracked-file secret scan, and `git diff --check` passed.
- Focused Azure DNS regression: 3 DNS guard tests passed, including timeout capacity retention.
- Frontend lint, 11 tests, and production build passed again after the backend change.
- PR #11 GitHub Actions passed across Python 3.10, 3.11, 3.12, 3.13, and Node 24. `Vercel Preview Comments` and the separate frontend Vercel deployment passed.
- An independent adversarial reviewer found no blocking defect in the fix. A theoretical callback limitation exists only if a nonstandard runner closes an event loop while executor work is pending; normal `asyncio.run` drains the default executor at shutdown.

## Findings and review

- Medium, independently confirmed: Azure endpoint validation wrapped `socket.getaddrinfo` in a 2-second thread timeout. A timeout cannot stop a resolver call already running in its worker thread, while provider capacity was released. Repeated slow lookups could occupy the shared executor. The public endpoints and current per-IP limiter reduce but do not eliminate this process-level availability risk. Python documents that running executor calls cannot be cancelled ([`Future.cancel`](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.Future.cancel)).
- Low, deferred: frontend utility tests exist, but React component and end-to-end user flows are not tested. No specific UI defect was confirmed.
- Low, deferred: the root README's backend quick-start uses Windows-only activation/copy commands even though backend README includes Unix instructions.
- Low, deferred: `backend/tests/test_ai_clients.py` includes an absolute 0.5-second performance assertion; no flake has been observed.
- No open GitHub issues were found.
- Nine open PRs are Dependabot updates. PRs #1 (FastAPI), #2 (Pydantic), #5 (httpx), #8 (ESLint), #9 (Uvicorn), and #10 (Ruff) have green GitHub Actions checks and are mergeable. PRs #4 and #6 split the React/React DOM 19 update and fail when installed independently due to incompatible peer versions. PR #3's Tailwind 4 update fails the frontend production build because the current PostCSS setup remains Tailwind 3 style. All nine show a failed Vercel app status; available status details do not establish its cause. No PR was merged or modified during triage.
- Dependabot alert inspection was unavailable: alerts are disabled for the repository, and the authenticated token lacks the additional scope requested by that endpoint.

## Implemented fixes

- Added a process-wide bounded Azure DNS admission semaphore, retained its slot until the resolver future finishes, shielded resolver work from request timeout/cancellation, and added a regression test. Committed as `919fee2` and pushed in [PR #11](https://github.com/asadbek066/ai-business-idea-validator/pull/11).

## Deferred work and risks

- Consider adding component-level frontend coverage when a maintainable DOM test setup is justified.
- Review whether to coordinate the React 19 dependency PRs and whether Tailwind 4 migration is desirable; both require dependency/configuration changes beyond a simple version bump.
- Determine why the Vercel check fails across PRs before treating those preview statuses as resolved.
- The legacy `Vercel – ai-business-idea-validator` status failed again on PR #11, while `Vercel – ai-business-idea-validator-frontend` passed. The Vercel CLI log command required an interactive account login unavailable in this environment, so the failure cause is not verified. GitHub Actions is green.
- DNS rebinding remains a deployment egress-policy concern documented by the project.

## Current campaign status

Status: PR_OPEN

Current branch: `codex/bound-azure-dns-lookups`.

Next action: continue portfolio discovery with repository #2; revisit the legacy Vercel status if Vercel access becomes available.
