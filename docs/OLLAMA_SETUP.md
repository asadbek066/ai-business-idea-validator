# Local AI Setup — Ollama

This guide gets you from zero to running the Business Idea Validator backend with a local LLM via Ollama.

---

## 1. Install Ollama

- **Windows / macOS / Linux:**  
  Download from [https://ollama.com](https://ollama.com) and run the installer.
- **Windows:** After install, Ollama usually runs in the background. You can also start it from the Start menu.
- **macOS:** Open the Ollama app from Applications; it will show in the menu bar when running.
- **Linux:**  
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```

Verify:

```bash
ollama --version
```

---

## 2. Start the Ollama server

- **Windows / macOS:** Often starts automatically. If not, open the Ollama app.
- **Terminal (any OS):**  
  ```bash
  ollama serve
  ```
  Leave this running. Default URL: `http://localhost:11434`.

Check it’s up:

```bash
curl http://localhost:11434/api/tags
```

You should get JSON listing models (or an empty list).

---

## 3. Download recommended models

Pull at least one model. Smaller = faster and less RAM; larger = better quality.

**Option A — Qwen 2.5 1.5B (default for this app, light and fast)**

```bash
ollama pull qwen2.5:1.5b
```

**Option B — Llama 3.2 (good balance)**

```bash
ollama pull llama3.2
```

**Option C — Phi-3 (lighter alternative)**

```bash
ollama pull phi3
```

List installed models:

```bash
ollama list
```

---

## 4. Test the Ollama API

Chat completion (same shape the backend uses):

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "qwen2.5:1.5b",
  "messages": [{"role": "user", "content": "Say hello in one sentence."}],
  "stream": false
}'
```

You should see a JSON response with a `message.content` field.

---

## 5. Connect the FastAPI backend to Ollama

1. **Start Ollama** (as in step 2).
2. **Backend env** (optional): in `backend/.env` set:
   - `OLLAMA_URL=http://localhost:11434` (default)
   - `OLLAMA_MODEL=qwen2.5:1.5b` (or `llama3.2`, `phi3`, etc.)
3. **Start the backend:**
   ```bash
   cd backend
   uvicorn app.main:app --reload --port 8000
   ```
4. **Test the full flow:**
   ```bash
   curl -X POST http://localhost:8000/analyze-idea -H "Content-Type: application/json" -d "{\"idea\": \"A coffee subscription for remote workers\"}"
   ```

You should get JSON with `market_potential`, `risks`, `first_steps`, and `verdict`.

---

## 6. Troubleshooting

| Issue | What to do |
|-------|------------|
| `ollama: command not found` | Reinstall Ollama and ensure it’s on your PATH. |
| `Connection refused` to `localhost:11434` | Start Ollama: run the app or `ollama serve`. |
| Backend returns 503 “No AI provider available” | Ensure Ollama is running and `OLLAMA_URL` is not set to `none`. |
| Slow first response | First run loads the model into RAM; subsequent calls are faster. |
| Out of memory | Use a smaller model (e.g. `qwen2.5:1.5b` or `phi3`). |

---

## 7. Using a different host/port

If Ollama runs on another machine or port:

```env
OLLAMA_URL=http://192.168.1.10:11434
OLLAMA_MODEL=qwen2.5:1.5b
```

Restart the FastAPI app after changing `.env`.
