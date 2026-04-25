"""
FastCite RAG Backend
- Embedding: sentence-transformers (local, free)
- Vector store: FAISS (in-memory, persisted to disk cache)
- LLM: Groq (free tier, Llama 3.1 8B)
- RAG variant: Naive RAG + metadata pre-filtering
"""

from dotenv import load_dotenv
load_dotenv()   # must be before any os.environ.get calls

import os
import json
import re
import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import faiss
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
KB_PATH        = Path(os.environ.get("KB_PATH", "./fastcite_knowledge_base"))
CACHE_DIR      = Path(".cache")          # stores embeddings between restarts
EMBED_MODEL    = "all-MiniLM-L6-v2"
GROQ_MODEL     = "llama-3.1-8b-instant"
TOP_K          = 4
MAX_CHUNK_TOKENS = 700
CHUNK_OVERLAP  = 2   # sentences

OUT_OF_SCOPE_KEYWORDS = [
    "divorce", "criminal", "murder", "property dispute", "immigration",
    "custody", "accident", "inheritance", "family law", "court case",
    "marriage registration", "nikah"
]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="FastCite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your GitHub Pages domain in prod
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ── Request / Response models ─────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    answer:  str
    steps:   list[str]
    source:  str
    warning: Optional[str] = None

# ── Knowledge Base Loader ─────────────────────────────────────────────────────
def load_kb_index(kb_path: Path) -> list[dict]:
    """Load kb_index.json for metadata-aware retrieval."""
    idx_path = kb_path / "metadata" / "kb_index.json"
    if not idx_path.exists():
        logger.warning("kb_index.json not found — metadata filtering disabled")
        return []
    with open(idx_path) as f:
        data = json.load(f)
    return data.get("documents", [])


def read_markdown(kb_path: Path, rel_path: str) -> str:
    """Read a KB document by its relative path."""
    full = kb_path / rel_path
    if not full.exists():
        logger.warning(f"KB file not found: {full}")
        return ""
    return full.read_text(encoding="utf-8")


def split_into_chunks(text: str, doc_meta: dict, max_chars: int = 2000, overlap_chars: int = 200) -> list[dict]:
    """
    Section-aware chunker: respects ## headings as split boundaries,
    then hard-splits oversized sections.
    Returns list of {text, source_label, doc_id, tags, keywords}
    """
    sections = re.split(r'\n(?=#{1,3} )', text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Extract heading for source label
        heading_match = re.match(r'#{1,3} (.+)', section)
        heading = heading_match.group(1).strip() if heading_match else ""
        # Hard-split large sections with overlap
        if len(section) <= max_chars:
            chunks.append({
                "text": section,
                "source_label": f"{doc_meta.get('id', '')} › {heading}" if heading else doc_meta.get('id', ''),
                "doc_id": doc_meta.get("id", ""),
                "topic": doc_meta.get("topic", ""),
                "tags": doc_meta.get("tags", []),
                "keywords": doc_meta.get("retrieval_keywords", []),
            })
        else:
            # Slide window
            start = 0
            while start < len(section):
                end = start + max_chars
                chunks.append({
                    "text": section[start:end],
                    "source_label": f"{doc_meta.get('id', '')} › {heading}" if heading else doc_meta.get('id', ''),
                    "doc_id": doc_meta.get("id", ""),
                    "topic": doc_meta.get("topic", ""),
                    "tags": doc_meta.get("tags", []),
                    "keywords": doc_meta.get("retrieval_keywords", []),
                })
                start += max_chars - overlap_chars
    return chunks


# ── Index Builder ─────────────────────────────────────────────────────────────
class RAGIndex:
    def __init__(self):
        self.chunks:    list[dict]   = []
        self.embeddings: np.ndarray | None = None
        self.faiss_index: faiss.IndexFlatIP | None = None
        self.embedder: SentenceTransformer | None = None

    def _cache_valid(self, kb_path: Path) -> bool:
        """Cache is valid if it exists and is newer than every KB file."""
        cache_index = CACHE_DIR / "faiss.index"
        cache_chunks = CACHE_DIR / "chunks.pkl"
        if not cache_index.exists() or not cache_chunks.exists():
            return False
        cache_mtime = min(cache_index.stat().st_mtime, cache_chunks.stat().st_mtime)
        # Invalidate if any KB markdown file is newer than cache
        for md_file in kb_path.rglob("*.md"):
            if md_file.stat().st_mtime > cache_mtime:
                logger.info(f"KB file changed: {md_file.name} — rebuilding cache")
                return False
        # Also invalidate if kb_index.json changed
        idx_file = kb_path / "metadata" / "kb_index.json"
        if idx_file.exists() and idx_file.stat().st_mtime > cache_mtime:
            logger.info("kb_index.json changed — rebuilding cache")
            return False
        return True

    def _save_cache(self):
        CACHE_DIR.mkdir(exist_ok=True)
        faiss.write_index(self.faiss_index, str(CACHE_DIR / "faiss.index"))
        with open(CACHE_DIR / "chunks.pkl", "wb") as f:
            pickle.dump(self.chunks, f)
        logger.info(f"Cache saved to {CACHE_DIR}/ ✓")

    def _load_cache(self):
        self.faiss_index = faiss.read_index(str(CACHE_DIR / "faiss.index"))
        with open(CACHE_DIR / "chunks.pkl", "rb") as f:
            self.chunks = pickle.load(f)
        logger.info(f"Loaded {len(self.chunks)} chunks from cache ✓")

    def build(self, kb_path: Path, doc_index: list[dict]):
        logger.info("Loading embedding model...")
        self.embedder = SentenceTransformer(EMBED_MODEL)

        # ── Use cache if KB hasn't changed ───────────────────────────────────
        if self._cache_valid(kb_path):
            logger.info("KB unchanged — loading from disk cache (fast start)")
            self._load_cache()
            return

        # ── Full rebuild ──────────────────────────────────────────────────────
        logger.info("Reading and chunking KB documents...")
        all_chunks = []
        for doc_meta in doc_index:
            rel_path = doc_meta.get("path", "")
            if not rel_path:
                continue
            text = read_markdown(kb_path, rel_path)
            if not text:
                continue
            chunks = split_into_chunks(text, doc_meta)
            all_chunks.extend(chunks)

        if not all_chunks:
            raise RuntimeError("No KB content loaded — check KB_PATH and kb_index.json paths")

        self.chunks = all_chunks
        logger.info(f"Total chunks: {len(self.chunks)}")

        texts = [c["text"] for c in self.chunks]
        logger.info("Encoding chunks (first run — will be cached after this)...")
        embeddings = self.embedder.encode(texts, normalize_embeddings=True, show_progress_bar=True)
        self.embeddings = embeddings.astype(np.float32)

        dim = self.embeddings.shape[1]
        self.faiss_index = faiss.IndexFlatIP(dim)   # Inner product ≡ cosine on normalized vecs
        self.faiss_index.add(self.embeddings)
        logger.info("FAISS index ready ✓")

        self._save_cache()

    def retrieve(self, query: str, top_k: int = TOP_K, keyword_boost_ids: list[str] | None = None) -> list[dict]:
        """
        Metadata-filtered + semantic retrieval.
        If keyword_boost_ids provided, scores from those doc_ids are boosted.
        """
        q_emb = self.embedder.encode([query], normalize_embeddings=True).astype(np.float32)
        scores, indices = self.faiss_index.search(q_emb, min(top_k * 3, len(self.chunks)))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            chunk = self.chunks[idx]
            boosted = 1.2 if (keyword_boost_ids and chunk["doc_id"] in keyword_boost_ids) else 1.0
            results.append({**chunk, "score": float(score) * boosted})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


# ── Global index (built at startup) ──────────────────────────────────────────
rag_index = RAGIndex()

@app.on_event("startup")
async def startup():
    doc_index = load_kb_index(KB_PATH)
    if not doc_index:
        logger.error("Empty doc_index — KB may not be found. Check KB_PATH env var.")
    rag_index.build(KB_PATH, doc_index)
    logger.info("RAG index built and ready.")


# ── Keyword → doc_id pre-filter ───────────────────────────────────────────────
KEYWORD_MAP = {
    "ntn":            ["fbr-ntn-registration", "fbr-freelancer-tax"],
    "national tax":   ["fbr-ntn-registration"],
    "strn":           ["fbr-strn-registration"],
    "sales tax":      ["fbr-strn-registration"],
    "freelanc":       ["fbr-freelancer-tax", "fbr-ntn-registration"],
    "secp":           ["secp-private-limited", "secp-single-member-company", "secp-sole-proprietorship"],
    "pvt ltd":        ["secp-private-limited", "comparisons-structure"],
    "private limited":["secp-private-limited", "comparisons-structure"],
    "smc":            ["secp-single-member-company", "comparisons-structure"],
    "single member":  ["secp-single-member-company"],
    "sole prop":      ["secp-sole-proprietorship", "comparisons-structure"],
    "partnership":    ["secp-partnership", "comparisons-structure"],
    "compliance":     ["compliance-checklist"],
    "annual":         ["compliance-checklist"],
    "deadline":       ["compliance-checklist"],
    "mistake":        ["common-mistakes"],
    "structure":      ["comparisons-structure"],
    "compare":        ["comparisons-structure"],
    "difference":     ["comparisons-structure"],
    "timeline":       ["incorporation-timeline"],
    "how long":       ["incorporation-timeline"],
    "employee":       ["employee-tax"],
    "hire":           ["employee-tax"],
    "reject":         ["recovery-appeals"],
    "appeal":         ["recovery-appeals"],
}

def keyword_boost_ids(query: str) -> list[str]:
    q = query.lower()
    ids = []
    for kw, doc_ids in KEYWORD_MAP.items():
        if kw in q:
            ids.extend(doc_ids)
    return list(set(ids))


# ── Groq LLM call ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are FastCite, a plain-language business law assistant for Pakistani founders and freelancers.
You ONLY answer questions about:
- SECP company registration (sole proprietorship, SMC, Pvt Ltd, partnership)
- FBR tax registration (NTN, STRN/STN)
- Business compliance in Pakistan

Rules:
1. Answer ONLY from the provided context chunks. Do not invent facts.
2. Use simple, clear English — no legal jargon unless you define it.
3. Always cite the source from context (e.g. "Source: FBR IRIS | Section 153(2)").
4. If context is insufficient, say so honestly and suggest the user verify at fbr.gov.pk or secp.gov.pk.
5. Structure your response as JSON with this exact schema:
{
  "answer": "plain-language explanation (1-3 sentences)",
  "steps": ["step 1", "step 2", ...],   // 0-6 concrete action steps, empty array if not applicable
  "source": "Source: [authority] | [section if known]",
  "warning": "optional caveat or disclaimer"   // null if none
}
Return ONLY the JSON object, no markdown fences, no preamble."""


def build_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[{i}] ({c['source_label']})\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def call_groq(query: str, context: str) -> dict:
    client = Groq(api_key=GROQ_API_KEY)
    user_msg = f"Context:\n{context}\n\nQuestion: {query}"
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip accidental markdown fences
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Groq returned non-JSON: {raw[:300]}")
        return {
            "answer": "I found relevant information but had trouble formatting the response. Please try rephrasing.",
            "steps": [],
            "source": "",
            "warning": "Response parsing error — try again."
        }
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        raise HTTPException(status_code=503, detail="LLM service unavailable")


# ── Main endpoint ─────────────────────────────────────────────────────────────
@app.post("/ask", response_model=QueryResponse)
async def ask(req: QueryRequest):
    query = req.query.strip()

    # 1. Basic validation
    if len(query) < 5:
        return QueryResponse(
            answer="Your question is too short. Please provide more detail.",
            steps=[],
            source="",
            warning=None
        )

    # 2. Out-of-scope detection
    q_lower = query.lower()
    if any(kw in q_lower for kw in OUT_OF_SCOPE_KEYWORDS):
        return QueryResponse(
            answer="This tool only covers Pakistani business registration and tax compliance (SECP, FBR, NTN, STRN). For other legal matters, please consult a qualified lawyer.",
            steps=[],
            source="",
            warning="Out of scope"
        )

    # 3. Metadata keyword boost
    boost_ids = keyword_boost_ids(query)

    # 4. Retrieve relevant chunks
    chunks = rag_index.retrieve(query, top_k=TOP_K, keyword_boost_ids=boost_ids or None)
    if not chunks:
        return QueryResponse(
            answer="I couldn't find relevant information in my knowledge base for that question.",
            steps=[],
            source="",
            warning="Please verify at fbr.gov.pk or secp.gov.pk"
        )

    # 5. Build context and call LLM
    context = build_context(chunks)
    result  = call_groq(query, context)

    return QueryResponse(
        answer  = result.get("answer", ""),
        steps   = result.get("steps", []),
        source  = result.get("source", ""),
        warning = result.get("warning"),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "chunks_indexed": len(rag_index.chunks)}