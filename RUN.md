# How to run FastCite

This document is the **full run guide** for the canonical app: **Groq + local embeddings + FAISS**, served by **`main.py` at the repository root**. The API and the chat UI (`frontend/`) run in **one process** when you start uvicorn.

---

## Prerequisites

- **Python 3.11+** recommended (matches `runtime.txt` / Render).
- A **Groq API key** (used for Llama chat completions). Sign up at [Groq Console](https://console.groq.com/) and create an API key.
- This repository, including the folder **`fastcite_knowledge_base/`** (with `metadata/kb_index.json`).

---

## 1. Open a terminal in the repo root

The working directory must be the folder that contains `main.py`, `requirements.txt`, and `fastcite_knowledge_base/`.

```text
fast-cite/
├── main.py
├── requirements.txt
├── .env.example
├── fastcite_knowledge_base/
└── frontend/
```

---

## 2. Create a virtual environment (recommended)

**Windows (PowerShell or Command Prompt):**

```bat
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 3. Install dependencies

Still in the repo root:

```bash
pip install -r requirements.txt
```

---

## 4. Configure environment variables

Copy the template and edit the real `.env` (do **not** commit `.env`; it stays local).

**Windows:**

```bat
copy .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

Edit `.env`:

| Variable        | Required | Purpose |
|----------------|----------|---------|
| `GROQ_API_KEY` | **Yes**  | Enables `POST /ask` (Groq LLM). If missing, installs may succeed but `/ask` can fail when calling Groq. |
| `KB_PATH`      | No       | Path to the knowledge base folder. Default is `./fastcite_knowledge_base` relative to **current working directory** when uvicorn starts. |

Example `.env`:

```env
GROQ_API_KEY=gsk_your_key_here
# KB_PATH=D:\path\to\fastcite_knowledge_base
```

Always start uvicorn from the repo root unless you set `KB_PATH` to an absolute path.

---

## 5. Start the server

**Development (auto-reload):**

```bash
uvicorn main:app --reload --port 8002
```

**Production-style (example):**

```bash
uvicorn main:app --host 0.0.0.0 --port 8002
```

**Render / cloud:** use **`uvicorn main:app --host 0.0.0.0 --port $PORT`** (required so Render detects the listener). Set `GROQ_API_KEY` in the dashboard. This repo pins **Python 3.11.9** (`.python-version` + `PYTHON_VERSION` in `render.yaml`). The Render **build** re-installs **`torch==2.3.1+cpu`** so Linux does not pull the multi‑GB CUDA stack. Free-tier RAM (~512 MiB) is tight: `render.yaml` sets **`FASTCITE_EMBED_MODEL=all-MiniLM-L3-v2`**, **`FASTCITE_ST_BATCH=4`**, and **`TORCH_NUM_THREADS=1`**. Out-of-memory at startup → use a tier with **≥1 GiB RAM** or run the API locally / on another host.

Optional env overrides (same variable names locally): **`FASTCITE_EMBED_MODEL`**, **`FASTCITE_ST_BATCH`**, **`FASTCITE_ST_PROGRESS`**, **`TORCH_NUM_THREADS`**.

---

## 6. Open the app

| URL | What it does |
|-----|----------------|
| [http://localhost:8002/](http://localhost:8002/) | Chat UI (static files from `frontend/`) |
| [http://localhost:8002/health](http://localhost:8002/health) | JSON: `status`, `chunks_indexed` |
| [http://localhost:8002/ask](http://localhost:8002/ask) | `POST` JSON body `{ "query": "…" }` — answer payload for the UI |
| [http://localhost:8002/docs](http://localhost:8002/docs) | FastAPI Swagger UI |

The browser UI uses **same-origin** `/ask` and `/health` by default—no extra frontend config needed when served from uvicorn.

---

## 7. First run expectations

On the **first** start after a clone (or after cache invalidation):

1. Sentence Transformer may download **`all-MiniLM-L6-v2`** (~tens of MB).
2. The app chunks the Markdown KB and builds a **FAISS** index.  
3. Cached data is stored under **`.cache/`** in the repo root (embedding index + chunks). Later starts are much faster unless you change KB files or `kb_index.json`.

Cold starts on **free-tier** hosts (e.g. after sleep) can take **well over 25 seconds**; the built-in frontend shows a short “slow start” message after ~5 seconds.

---

## 8. Verify with curl / PowerShell

**Health:**

```bash
curl http://localhost:8002/health
```

**Ask (bash / macOS / Linux):**

```bash
curl -X POST http://localhost:8002/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "Do I need NTN for freelancing?"}'
```

**Ask (PowerShell):**

```powershell
Invoke-RestMethod -Uri "http://localhost:8002/ask" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query": "Do I need NTN for freelancing?"}'
```

Successful responses match the UI shape: `answer`, `steps`, `source`, optional `warning`.

---

## 9. Hosting the frontend separately (GitHub Pages, etc.)

If `index.html` is **not** served by the same host as the API:

1. In the browser console before using the app:  
   `localStorage.setItem('FASTCITE_API_BASE', 'https://your-api.example.com')`  
   then reload, **or**
2. Open the site with  
   `?api=https://your-api.example.com`

Requests go to `{base}/health` and `{base}/ask`.

---

## 10. Offline-style demo (no Groq)

Not a substitute for real answers. To show canned replies when the API is unreachable:

- Add **`?mock=1`** to the page URL, or  
- `localStorage.setItem('fastcite_mock', '1')` and reload.

---

## 11. Troubleshooting

| Symptom | What to check |
|---------|----------------|
| `chunks_indexed` is 0 or errors in logs | `KB_PATH`, presence of `fastcite_knowledge_base/metadata/kb_index.json`, readable Markdown paths in that index. |
| `/ask` errors or empty bad responses | `GROQ_API_KEY` in `.env`, Groq quota / key validity. |
| UI says “Backend offline” | Server not running, wrong port, or (if static hosting) missing `FASTCITE_API_BASE` / `?api=`. |
| Very slow first request | Model download + FAISS build; or host waking from sleep—wait or use a paid/warm instance. |

---

## 12. Alternate stack (not this guide)

The **`backend/`** folder is an optional **Qdrant + Gemini** implementation. It is **not** started with `main.py`. See [`backend/README.md`](backend/README.md) if you use that stack instead.

---

## Quick reference (copy-paste)

```bash
cd /path/to/fast-cite
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
# Edit .env — set GROQ_API_KEY
uvicorn main:app --reload --port 8002
# Browser: http://localhost:8002/
```
