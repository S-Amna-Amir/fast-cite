# FastCite — Pakistan business registration assistant

Groq-hosted LLM + local **sentence-transformers** embeddings + **FAISS** over the Markdown knowledge base under `fastcite_knowledge_base/`. The FastAPI app at the **repository root** also serves the static UI from [`frontend/`](frontend/) — one process for chat + API.

**Step-by-step from zero:** see [**RUN.md**](RUN.md).

## Local development

```bash
python -m venv venv
# Windows:
venv\Scripts\activate

pip install -r requirements.txt

# Copy secrets (see .env.example)
copy .env.example .env    # Windows; then edit .env and set GROQ_API_KEY=

uvicorn main:app --reload --port 8002
```

Then open **http://localhost:8002/** for the UI, or probe the API directly:

- `GET http://localhost:8002/health` → `{"status":"ok","chunks_indexed":…}`
- `POST http://localhost:8002/ask` with JSON `{"query": "…"}`

First startup may download the embedding model and build `.cache/` (FAISS + chunk payload). Subsequent starts reuse the cache until the KB or `kb_index.json` changes.

### Frontend pointing at another API

If you host the static files elsewhere (for example GitHub Pages), either:

1. Before loading the app, run in the browser console:  
   `localStorage.setItem('FASTCITE_API_BASE', 'https://your-render-service.onrender.com')`  
   then reload — the UI will call that origin for `/health` and `/ask`, **or**

2. Open the app with a query parameter:  
   `?api=https://your-render-service.onrender.com`

Offline demo replies (no Groq required) are gated: add `?mock=1` to the URL or set `localStorage.setItem('fastcite_mock','1')`.

## Deploy API + UI together (Render)

The repo includes [`render.yaml`](render.yaml): connect the repo, add `GROQ_API_KEY` in the dashboard (mark as secret), deploy.

**Python version:** Render’s default is now **3.14**. This project pins **3.11.9** via [`.python-version`](.python-version) and `PYTHON_VERSION` in `render.yaml` so `numpy`/`faiss-cpu` install from wheels instead of compiling for minutes. If you created the service manually, set **Environment → `PYTHON_VERSION` = `3.11.9`** (or redeploy from the blueprint).

Cold starts on free tier can exceed 25s — the frontend shows an automatic “slow start” hint after five seconds while waiting.

Alternatively, host only **`frontend/`** on GitHub Pages and set **`FASTCITE_API_BASE`** to your deployed API URL using one of the methods above.

## Repo layout

```
your-repo/
├── main.py                 ← FastAPI: /health, /ask, static frontend/
├── render.yaml             ← Render (optional)
├── requirements.txt        ← Root Python deps (Groq, FAISS, ST, FastAPI…)
├── .env.example
├── fastcite_knowledge_base/
│   ├── metadata/kb_index.json
│   └── …
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

## Alternate backend

[`backend/README.md`](backend/README.md) documents an optional **Qdrant + Gemini** stack — **not** the default path described here.

## RAG flow

1. Keyword list rejects clearly out-of-scope topics (family/criminal/etc.).
2. Query keywords optionally boost retrieval from mapped `doc_id`s in [`kb_index.json`](fastcite_knowledge_base/metadata/kb_index.json).
3. MiniLM cosine search returns top chunks.
4. Groq Llama writes structured JSON (`answer`, `steps`, `source`, `warning`).

## Debugging

```bash
curl http://localhost:8002/health

curl -X POST http://localhost:8002/ask ^
  -H "Content-Type: application/json" ^
  -d "{\"query\": \"Do I need NTN for freelancing?\"}"
```
*(Use `\` continuation on bash/macOS.)*
