# FastCite — Qdrant + Gemini backend (non-default)

This directory contains an **alternate** FastCite backend: Sentence Transformer embeddings uploaded to **Qdrant**, with answers from the **Gemini API** (`backend/app/`).

**The canonical app you should run for local development and the Render blueprint in this repo is the Groq + FAISS server at the repository root** ([`main.py`](../main.py)).

Use this backend only if you explicitly want Gemini + hosted Qdrant. It requires Python dependencies from [`backend/requirements.txt`](requirements.txt), a Qdrant instance, `GEMINI_API_KEY`, and a separate uvicorn invocation (for example `uvicorn app.main:app` with working directory `backend/` and appropriate `PYTHONPATH`).
