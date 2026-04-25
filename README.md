# FastCite Backend — Deployment Guide

## Local Development

```bash
# 1. Clone / set up
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Add your Groq key
echo "GROQ_API_KEY=gsk_your_key_here" > .env

# 4. Run
uvicorn main:app --reload --port 8002
# → http://localhost:8002/health   should return {"status":"ok","chunks_indexed":N}
# → Update frontend/app.js API_URL to http://localhost:8002/ask
```

## Deploying Backend to Render (Free)

1. Push your repo to GitHub:
   ```
   your-repo/
   ├── main.py
   ├── requirements.txt
   ├── render.yaml
   └── fastcite_knowledge_base/   ← the whole KB folder
   ```

2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects render.yaml
5. In Render dashboard → Environment → Add:
   - `GROQ_API_KEY` = your Groq key
6. Deploy → get a URL like `https://fastcite-api.onrender.com`

**Important:** Render free tier sleeps after 15 min inactivity.
First request after sleep takes ~25-35s (embedding model cold-start).
Add this 1-liner to your frontend to show a "waking up..." message if
the request takes > 5s.

## Deploying Frontend to GitHub Pages

1. Put `index.html`, `app.js`, `style.css` in `/docs` folder (or root)
2. In `app.js` change:
   ```js
   const API_URL = 'https://fastcite-api.onrender.com/ask';
   ```
3. GitHub repo → Settings → Pages → Source: main branch / docs folder
4. Done — free HTTPS hosting at `https://yourusername.github.io/fastcite`

## Repo Structure

```
your-repo/
├── main.py                         ← FastAPI backend
├── requirements.txt
├── render.yaml
├── fastcite_knowledge_base/
│   ├── metadata/kb_index.json      ← CRITICAL: must exist
│   ├── fbr/
│   ├── secp/
│   ├── comparisons/
│   └── ...
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

## RAG Architecture

**Variant:** Naive RAG + Metadata Pre-filtering

```
Query
  │
  ├─ Out-of-scope check (keyword list) → early exit if divorce/criminal/etc.
  │
  ├─ Keyword → doc_id boost map       → metadata pre-filter using kb_index.json tags
  │
  ├─ FAISS semantic search            → cosine similarity on MiniLM embeddings
  │   (top-4 chunks, boosted if matching pre-filter)
  │
  ├─ Context assembly                 → chunk text + source_label injected into prompt
  │
  └─ Groq Llama 3.1 8B               → structured JSON output (answer/steps/source/warning)
```

## Debugging

```bash
# Check what chunks were built
curl http://localhost:8002/health

# Test the /ask endpoint directly
curl -X POST http://localhost:8002/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "Do I need NTN for freelancing?"}'
```
