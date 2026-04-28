"""
rag_service.py  —  Production-ready RAG for the interview-prep FastAPI app.

===== SUPABASE SQL SETUP (run once in Supabase SQL editor) =====

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create knowledge_chunks table
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT,                          -- NULL = global knowledge, user UUID = private
    source        TEXT NOT NULL,                 -- filename or URL the chunk came from
    topic         TEXT,                          -- e.g. "arrays", "system design", "behavioral"
    content       TEXT NOT NULL,                 -- raw chunk text
    embedding     VECTOR(384),                   -- all-MiniLM-L6-v2 produces 384-dim vectors
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 3. ivfflat cosine similarity index (recreate after bulk loads)
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
    ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- 4. Helper: cosine similarity search (called via supabase.rpc)
CREATE OR REPLACE FUNCTION match_knowledge_chunks(
    query_embedding VECTOR(384),
    match_count     INT     DEFAULT 5,
    filter_topic    TEXT    DEFAULT NULL,
    filter_user_id  TEXT    DEFAULT NULL,
    score_threshold FLOAT   DEFAULT 0.30
)
RETURNS TABLE (
    id         BIGINT,
    source     TEXT,
    topic      TEXT,
    content    TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        kc.id,
        kc.source,
        kc.topic,
        kc.content,
        1 - (kc.embedding <=> query_embedding) AS similarity
    FROM knowledge_chunks kc
    WHERE
        (filter_topic   IS NULL OR kc.topic     = filter_topic)
        AND
        (filter_user_id IS NULL OR kc.user_id   = filter_user_id OR kc.user_id IS NULL)
        AND
        1 - (kc.embedding <=> query_embedding) >= score_threshold
    ORDER BY kc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

===== ENVIRONMENT VARIABLES (.env) =====
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
OPENAI_API_KEY=sk-...          # Used ONLY for answer generation (optional if using local LLM)
EMBEDDING_MODEL=all-MiniLM-L6-v2   # sentence-transformers model name
RAG_TOP_K=5                    # default number of chunks to retrieve
RAG_SCORE_THRESHOLD=0.30       # minimum cosine similarity to include a chunk

===== REQUIREMENTS ADDITIONS =====
sentence-transformers>=2.7.0
openai>=1.30.0
httpx>=0.27.0          # already in your project
supabase>=2.4.0        # already in your project
pdfplumber>=0.10.0     # already in your project
python-dotenv>=1.0.0   # already in your project
numpy>=1.26.0

pip install sentence-transformers openai   # minimal additions

===== WINDOWS POWERSHELL RUN INSTRUCTIONS =====
1.  cd your-backend-folder
2.  python -m venv .venv
3.  .\.venv\Scripts\Activate.ps1
4.  pip install -r requirements.txt
5.  pip install sentence-transformers openai
6.  # Ingest documents once:
    python rag_service.py
7.  # Then start FastAPI as normal:
    uvicorn main:app --reload

"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np
import pdfplumber
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import Client, create_client

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("rag_service")

# ---------------------------------------------------------------------------
# Configuration (all read from .env with sensible defaults)
# ---------------------------------------------------------------------------

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))
RAG_SCORE_THRESHOLD: float = float(os.getenv("RAG_SCORE_THRESHOLD", "0.30"))
OPENAI_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

# Chunk parameters
DEFAULT_CHUNK_SIZE: int = 500       # characters per chunk
DEFAULT_CHUNK_OVERLAP: int = 80     # overlap between consecutive chunks

# Lazy-loaded singletons
_supabase_client: Optional[Client] = None
_embedding_model: Optional[SentenceTransformer] = None

# ---------------------------------------------------------------------------
# Fallback response when retrieval is weak
# ---------------------------------------------------------------------------

RAG_FALLBACK_RESPONSE = (
    "I don't have enough specific context in my knowledge base to answer that confidently. "
    "Here's what I'd suggest: review the official documentation or a trusted resource on this topic, "
    "or rephrase your question with more detail so I can search more precisely. "
    "You can also try asking me about a specific data structure, algorithm, or system design concept."
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_clients() -> Tuple[Client, SentenceTransformer]:
    """
    Initialise (and cache) the Supabase client and the embedding model.

    Returns
    -------
    (supabase_client, embedding_model)
    """
    global _supabase_client, _embedding_model

    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
            )
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client ready")

    if _embedding_model is None:
        logger.info("Loading embedding model: %s  (first load may take ~30 s)", EMBEDDING_MODEL_NAME)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info("Embedding model loaded. Vector dim: %d", _embedding_model.get_sentence_embedding_dimension())

    return _supabase_client, _embedding_model


# ---------------------------------------------------------------------------
# Step 1 — Document loading
# ---------------------------------------------------------------------------


def load_documents(path: str | Path) -> List[Dict[str, Any]]:
    """
    Recursively load .txt, .md, and .pdf files from *path* (file or directory).

    Returns
    -------
    List of dicts with keys: source (str), topic (str | None), content (str)
    """
    root = Path(path)
    docs: List[Dict[str, Any]] = []

    targets: List[Path] = [root] if root.is_file() else list(root.rglob("*"))

    for file_path in targets:
        if file_path.suffix.lower() not in {".txt", ".md", ".pdf"}:
            continue

        try:
            content = _read_file(file_path)
        except Exception as exc:
            logger.warning("Skipping %s: %s", file_path, exc)
            continue

        if not content.strip():
            logger.warning("Empty content in %s, skipping", file_path)
            continue

        topic = _infer_topic_from_path(file_path)
        docs.append(
            {
                "source": str(file_path),
                "topic": topic,
                "content": content,
            }
        )
        logger.info("Loaded %s  (%d chars, topic=%s)", file_path.name, len(content), topic)

    logger.info("Total documents loaded: %d", len(docs))
    return docs


def _read_file(file_path: Path) -> str:
    """Read file content, handling pdf separately."""
    if file_path.suffix.lower() == ".pdf":
        return _extract_pdf_text(file_path)
    return file_path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf_text(file_path: Path) -> str:
    """Extract plain text from a PDF using pdfplumber (already in your deps)."""
    parts: List[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages[:50]:  # cap at 50 pages
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _infer_topic_from_path(file_path: Path) -> Optional[str]:
    """
    Best-effort: derive a topic label from filename or parent folder name.
    e.g. docs/arrays/two-sum.md  ->  "arrays"
         system_design.txt       ->  "system design"
    """
    known_topics = {
        "array": "arrays",
        "arrays": "arrays",
        "linked-list": "linked lists",
        "linked_list": "linked lists",
        "tree": "trees",
        "trees": "trees",
        "graph": "graphs",
        "graphs": "graphs",
        "dynamic-programming": "dynamic programming",
        "dp": "dynamic programming",
        "sorting": "sorting",
        "searching": "searching",
        "system-design": "system design",
        "system_design": "system design",
        "behavioral": "behavioral",
        "os": "operating systems",
        "database": "databases",
        "sql": "databases",
        "oop": "oop",
        "devops": "devops",
    }
    candidates = [file_path.stem.lower(), file_path.parent.name.lower()]
    for candidate in candidates:
        slug = re.sub(r"[^a-z0-9\-_]", "", candidate)
        if slug in known_topics:
            return known_topics[slug]
    return None


# ---------------------------------------------------------------------------
# Step 2 — Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """
    Split *text* into overlapping character-level chunks.

    Tries to break at sentence/paragraph boundaries first; falls back to
    hard character splits if necessary.

    Parameters
    ----------
    text       : raw document content
    chunk_size : target chunk length in characters
    overlap    : number of characters to repeat between adjacent chunks
    """
    if not text or not text.strip():
        return []

    # Normalise whitespace but preserve paragraph breaks
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Split into natural segments (paragraphs / sentences)
    segments: List[str] = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    current = ""

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        if len(current) + len(segment) + 1 <= chunk_size:
            current = (current + "\n\n" + segment).lstrip()
        else:
            if current:
                chunks.append(current.strip())
            # Segment itself may be longer than chunk_size — hard-split it
            if len(segment) > chunk_size:
                for start in range(0, len(segment), chunk_size - overlap):
                    piece = segment[start : start + chunk_size]
                    if piece.strip():
                        chunks.append(piece.strip())
                current = ""
            else:
                current = segment

    if current.strip():
        chunks.append(current.strip())

    # De-duplicate (identical consecutive chunks can appear with small docs)
    seen: set[str] = set()
    unique: List[str] = []
    for chunk in chunks:
        key = chunk[:80]  # compare first 80 chars as fingerprint
        if key not in seen:
            seen.add(key)
            unique.append(chunk)

    logger.debug("Chunked into %d segments (chunk_size=%d, overlap=%d)", len(unique), chunk_size, overlap)
    return unique


# ---------------------------------------------------------------------------
# Step 3 — Embedding
# ---------------------------------------------------------------------------


def embed_chunks(chunks: List[str]) -> np.ndarray:
    """
    Encode a list of text chunks into float32 numpy vectors.

    Returns
    -------
    np.ndarray of shape (len(chunks), embedding_dim)
    """
    if not chunks:
        return np.array([], dtype=np.float32).reshape(0, 384)

    _, model = init_clients()

    logger.info("Embedding %d chunks…", len(chunks))
    embeddings: np.ndarray = model.encode(
        chunks,
        batch_size=32,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,  # unit-norm for cosine similarity
    )
    logger.info("Embedding done. Shape: %s", embeddings.shape)
    return embeddings.astype(np.float32)


# ---------------------------------------------------------------------------
# Step 4 — Upsert into Supabase pgvector
# ---------------------------------------------------------------------------


def upsert_chunks(
    chunks: List[str],
    embeddings: np.ndarray,
    metadata: Dict[str, Any],
    batch_size: int = 50,
) -> int:
    """
    Insert (or replace) chunks + embeddings into the knowledge_chunks table.

    Parameters
    ----------
    chunks     : list of raw text chunks
    embeddings : numpy array matching len(chunks)
    metadata   : dict with keys: source (required), topic (optional), user_id (optional)
    batch_size : rows per Supabase insert call

    Returns
    -------
    Number of rows upserted
    """
    if not chunks:
        logger.warning("upsert_chunks called with empty chunks list")
        return 0

    client, _ = init_clients()
    source: str = metadata.get("source", "unknown")
    topic: Optional[str] = metadata.get("topic")
    user_id: Optional[str] = metadata.get("user_id")
    now = _utcnow_iso()

    rows: List[Dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings):
        row: Dict[str, Any] = {
            "source": source,
            "content": chunk,
            "embedding": embedding.tolist(),
            "created_at": now,
            "updated_at": now,
        }
        if topic:
            row["topic"] = topic
        if user_id:
            row["user_id"] = user_id
        rows.append(row)

    total_inserted = 0
    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start : batch_start + batch_size]
        try:
            result = client.table("knowledge_chunks").insert(batch).execute()
            inserted = len(getattr(result, "data", None) or [])
            total_inserted += inserted
            logger.info(
                "Upserted batch %d-%d (%d rows) for source=%s",
                batch_start,
                batch_start + len(batch) - 1,
                inserted,
                source,
            )
        except Exception as exc:
            logger.error("Batch upsert failed for %s at row %d: %s", source, batch_start, exc)

    return total_inserted


# ---------------------------------------------------------------------------
# Step 5 — Retrieval
# ---------------------------------------------------------------------------


def retrieve_context(
    query: str,
    user_id: Optional[str] = None,
    topic: Optional[str] = None,
    top_k: int = RAG_TOP_K,
    score_threshold: float = RAG_SCORE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Embed *query* and fetch the most semantically similar chunks.

    Parameters
    ----------
    query          : the user's question
    user_id        : if provided, prioritise private chunks for this user
    topic          : optional filter (e.g. "arrays", "system design")
    top_k          : number of results to return
    score_threshold: minimum cosine similarity (0-1) to include a result

    Returns
    -------
    List of dicts with keys: id, source, topic, content, similarity
    Sorted by similarity descending.
    """
    if not query or not query.strip():
        return []

    _, model = init_clients()
    client, _ = init_clients()

    # Embed query
    query_vec: np.ndarray = model.encode(
        [query.strip()],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0].astype(np.float32)

    # Call the Postgres function we created in the SQL setup
    try:
        result = client.rpc(
            "match_knowledge_chunks",
            {
                "query_embedding": query_vec.tolist(),
                "match_count": top_k,
                "filter_topic": topic,
                "filter_user_id": user_id,
                "score_threshold": score_threshold,
            },
        ).execute()
    except Exception as exc:
        logger.error("retrieve_context RPC failed: %s", exc)
        return []

    rows: List[Dict[str, Any]] = getattr(result, "data", None) or []
    logger.info(
        "Retrieved %d chunks for query='%s…' (topic=%s, user_id=%s)",
        len(rows),
        query[:40],
        topic,
        user_id,
    )
    return rows


# ---------------------------------------------------------------------------
# Step 6 — Answer generation
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert interview preparation coach specialising in Data Structures, Algorithms, System Design, and Behavioural interviews.

You MUST answer using ONLY the provided context chunks. Do not add facts not present in the context.
If the context does not contain enough information, say exactly: "I don't have enough specific context for this question."

Format your response in this structure:
1. A clear, direct answer (2-5 sentences).
2. A concrete example or code snippet if relevant.
3. One follow-up tip or related concept the candidate should study.

Keep your total response under 350 words.
"""


def generate_rag_answer(
    query: str,
    retrieved_chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, str]]] = None,
    weak_topics: Optional[List[str]] = None,
    readiness_score: Optional[int] = None,
    learning_goal: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a grounded answer from the retrieved context chunks using an LLM.

    Falls back gracefully when:
    - No chunks are retrieved (score too low)
    - OpenAI key is missing (returns offline answer)
    - API call fails

    Parameters
    ----------
    query             : original user question
    retrieved_chunks  : output of retrieve_context()
    conversation_history : list of {"role": "user"|"assistant", "content": str}
    weak_topics       : user's weak areas for personalisation hints
    readiness_score   : 0-100 readiness score for personalisation
    learning_goal     : e.g. "Google SWE L4"

    Returns
    -------
    {
        "answer": str,
        "sources": [{"source": str, "topic": str, "similarity": float, "excerpt": str}],
        "confidence": float,   # average similarity of top chunks, 0-1
        "fallback": bool,      # True if we used the fallback response
    }
    """
    # --- Guard: no useful context retrieved ---
    if not retrieved_chunks:
        logger.warning("No chunks retrieved — returning fallback response")
        return {
            "answer": RAG_FALLBACK_RESPONSE,
            "sources": [],
            "confidence": 0.0,
            "fallback": True,
        }

    avg_similarity = sum(float(c.get("similarity", 0.0)) for c in retrieved_chunks) / len(retrieved_chunks)

    if avg_similarity < score_threshold_for_answer():
        logger.warning("Low average similarity %.3f — returning fallback", avg_similarity)
        return {
            "answer": RAG_FALLBACK_RESPONSE,
            "sources": _build_sources(retrieved_chunks),
            "confidence": round(avg_similarity, 3),
            "fallback": True,
        }

    # --- Compose context block ---
    context_parts: List[str] = []
    for i, chunk in enumerate(retrieved_chunks, start=1):
        topic_tag = f"[topic: {chunk['topic']}] " if chunk.get("topic") else ""
        context_parts.append(f"--- Chunk {i} {topic_tag}---\n{chunk['content']}")
    context_block = "\n\n".join(context_parts)

    # --- Optional personalisation addendum ---
    personalisation = _build_personalisation_note(weak_topics, readiness_score, learning_goal)

    # --- Build messages ---
    messages: List[Dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    # Include recent conversation turns for context (max last 6)
    if conversation_history:
        for turn in conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})

    user_message = (
        f"Context from knowledge base:\n{context_block}\n\n"
        f"{personalisation}"
        f"Question: {query}"
    )
    messages.append({"role": "user", "content": user_message})

    # --- Call OpenAI (or fallback to offline) ---
    answer = _call_openai(messages)

    return {
        "answer": answer,
        "sources": _build_sources(retrieved_chunks),
        "confidence": round(avg_similarity, 3),
        "fallback": False,
    }


def score_threshold_for_answer() -> float:
    """Configurable minimum average similarity before we trust retrieval."""
    return float(os.getenv("RAG_ANSWER_THRESHOLD", str(RAG_SCORE_THRESHOLD)))


def _build_personalisation_note(
    weak_topics: Optional[List[str]],
    readiness_score: Optional[int],
    learning_goal: Optional[str],
) -> str:
    parts: List[str] = []
    if weak_topics:
        parts.append(f"The user's weak topics are: {', '.join(weak_topics[:5])}.")
    if readiness_score is not None:
        parts.append(f"Their current readiness score is {readiness_score}/100.")
    if learning_goal:
        parts.append(f"Their learning goal: {learning_goal}.")
    if parts:
        return "Personalisation context: " + " ".join(parts) + "\n\n"
    return ""


def _build_sources(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract citation-friendly metadata from retrieved chunks."""
    sources: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        src = chunk.get("source", "unknown")
        if src in seen:
            continue
        seen.add(src)
        sources.append(
            {
                "source": src,
                "topic": chunk.get("topic"),
                "similarity": round(float(chunk.get("similarity", 0.0)), 3),
                "excerpt": (chunk.get("content", "")[:200] + "…") if chunk.get("content") else "",
            }
        )
    return sources


def _call_openai(messages: List[Dict[str, str]]) -> str:
    """
    Call OpenAI chat completions.
    Falls back to a descriptive offline message when key is absent or API fails.
    """
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — using offline fallback answer")
        return _offline_answer_from_messages(messages)

    try:
        import openai  # local import so the module loads without openai installed

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.3,
            max_tokens=600,
        )
        answer: str = response.choices[0].message.content or ""
        return answer.strip()
    except Exception as exc:
        logger.error("OpenAI API call failed: %s", exc)
        return _offline_answer_from_messages(messages)


def _offline_answer_from_messages(messages: List[Dict[str, str]]) -> str:
    """
    When OpenAI is unavailable, extract and return the raw context so the
    user still gets something useful.
    """
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            # Strip personalisation header, return context block
            if "Context from knowledge base:" in content:
                context_section = content.split("Question:")[0]
                context_section = context_section.replace("Context from knowledge base:\n", "").strip()
                return (
                    "Here is the relevant knowledge I found (LLM generation unavailable):\n\n"
                    + context_section[:800]
                )
    return RAG_FALLBACK_RESPONSE


# ---------------------------------------------------------------------------
# Step 7 — Main entry point for /doubts/chat
# ---------------------------------------------------------------------------


def answer_with_rag(
    query: str,
    user_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    End-to-end RAG answer function.  Call this from main.py inside /doubts/chat.

    Parameters
    ----------
    query        : the user's message (request.message)
    user_context : dict with optional keys:
                   - user_id (str)
                   - weak_topics (list[str])
                   - readiness_score (int)
                   - learning_goal (str)
                   - conversation_history (list[dict])
                   - topic (str)   — pass if you can infer a topic filter

    Returns
    -------
    Dict compatible with DoubtChatResponse plus an extra "sources" field:
    {
        "response": str,
        "section": str,
        "practice_question": None,
        "difficulty_level": str,
        "suggestions": list[str],
        "sources": list[dict],        # <-- new field
        "confidence": float,          # <-- new field
        "rag_used": bool,             # <-- new field (True = RAG answered it)
    }
    """
    user_id: Optional[str] = user_context.get("user_id")
    weak_topics: List[str] = user_context.get("weak_topics") or []
    readiness_score: Optional[int] = user_context.get("readiness_score")
    learning_goal: Optional[str] = user_context.get("learning_goal")
    history: List[Dict[str, str]] = user_context.get("conversation_history") or []
    topic_filter: Optional[str] = user_context.get("topic")

    try:
        # 1. Retrieve
        chunks = retrieve_context(
            query=query,
            user_id=user_id,
            topic=topic_filter,
            top_k=RAG_TOP_K,
        )

        # 2. Generate grounded answer
        rag_result = generate_rag_answer(
            query=query,
            retrieved_chunks=chunks,
            conversation_history=history,
            weak_topics=weak_topics,
            readiness_score=readiness_score,
            learning_goal=learning_goal,
        )

        answer_text: str = rag_result["answer"]
        fallback: bool = rag_result["fallback"]
        confidence: float = rag_result["confidence"]
        sources: List[Dict[str, Any]] = rag_result["sources"]

        # 3. Build follow-up suggestions based on sources
        suggestions = _build_suggestions(chunks, weak_topics, fallback)

        # 4. Detect difficulty level (simple heuristic)
        difficulty = _detect_difficulty(query)

        return {
            "response": answer_text,
            "section": "rag_answer" if not fallback else "fallback",
            "practice_question": None,
            "difficulty_level": difficulty,
            "suggestions": suggestions,
            "sources": sources,
            "confidence": confidence,
            "rag_used": not fallback,
        }

    except Exception as exc:
        logger.error("answer_with_rag failed for query='%s': %s", query[:60], exc, exc_info=True)
        return {
            "response": RAG_FALLBACK_RESPONSE,
            "section": "fallback",
            "practice_question": None,
            "difficulty_level": "intermediate",
            "suggestions": ["Try rephrasing your question", "Ask about a specific topic"],
            "sources": [],
            "confidence": 0.0,
            "rag_used": False,
        }


def _build_suggestions(
    chunks: List[Dict[str, Any]],
    weak_topics: List[str],
    fallback: bool,
) -> List[str]:
    suggestions: List[str] = []
    if not fallback:
        topics_found = {c.get("topic") for c in chunks if c.get("topic")}
        for t in list(topics_found)[:2]:
            suggestions.append(f"Ask me to give you a practice problem on {t}")
    if weak_topics:
        suggestions.append(f"Want to drill your weak area: {weak_topics[0]}?")
    suggestions.append("Ask me to explain the time complexity of this concept")
    return suggestions[:3]


def _detect_difficulty(query: str) -> str:
    q = query.lower()
    if any(k in q for k in ("what is", "define", "explain simply", "basics", "beginner")):
        return "beginner"
    if any(k in q for k in ("optimize", "edge case", "production", "scale", "architecture")):
        return "advanced"
    return "intermediate"


# ---------------------------------------------------------------------------
# Ingestion helper — run from __main__ to ingest a local folder
# ---------------------------------------------------------------------------


def ingest_folder(
    folder_path: str | Path,
    user_id: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> Dict[str, Any]:
    """
    Convenience wrapper: load → chunk → embed → upsert for an entire folder.

    Parameters
    ----------
    folder_path : path to local docs directory
    user_id     : if set, chunks are stored as private to this user
    chunk_size  : character count per chunk
    overlap     : overlap between chunks

    Returns
    -------
    Summary dict: { documents: int, chunks: int, upserted: int }
    """
    init_clients()
    docs = load_documents(folder_path)
    total_chunks = 0
    total_upserted = 0

    for doc in docs:
        chunks = chunk_text(doc["content"], chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            continue
        embeddings = embed_chunks(chunks)
        upserted = upsert_chunks(
            chunks=chunks,
            embeddings=embeddings,
            metadata={
                "source": doc["source"],
                "topic": doc["topic"],
                "user_id": user_id,
            },
        )
        total_chunks += len(chunks)
        total_upserted += upserted
        logger.info(
            "✓  %s  →  %d chunks  →  %d upserted",
            Path(doc["source"]).name,
            len(chunks),
            upserted,
        )

    summary = {
        "documents": len(docs),
        "chunks": total_chunks,
        "upserted": total_upserted,
    }
    logger.info("Ingestion complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# main.py integration — copy these two blocks into your main.py
# ---------------------------------------------------------------------------

MAIN_PY_INTEGRATION = """
# ---- ADD TO main.py --------------------------------------------------------

# 1. Import at top of main.py (alongside existing imports):
from rag_service import answer_with_rag

# 2. Update DoubtChatResponse model to add optional fields:
class DoubtChatResponse(BaseModel):
    response: str
    section: Optional[str] = None
    practice_question: Optional[str] = None
    difficulty_level: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    # --- NEW fields (backwards-compatible, both optional) ---
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Optional[float] = None
    rag_used: Optional[bool] = None

# 3. Replace the body of the /doubts/chat endpoint:
@app.post("/doubts/chat")
async def doubts_chat(
    request: DoubtChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> DoubtChatResponse:
    try:
        user_id = current_user.get("id") or current_user.get("user_id")

        # --- RAG path (new) ---
        rag_result = answer_with_rag(
            query=request.message,
            user_context={
                "user_id": user_id,
                "weak_topics": request.weak_topics,
                "readiness_score": request.readiness_score,
                "learning_goal": request.learning_goal,
                "conversation_history": request.conversation_history,
            },
        )

        # If RAG had strong retrieval, return grounded answer
        if rag_result.get("rag_used"):
            return DoubtChatResponse(**rag_result)

        # Else fall back to your existing LearningAssistant heuristic
        response = learning_assistant.generate_response(
            user_message=request.message,
            conversation_history=request.conversation_history,
            user_id=user_id,
            weak_topics=request.weak_topics,
            readiness_score=request.readiness_score,
            learning_goal=request.learning_goal,
        )
        return response

    except Exception as e:
        logger.error(f"Error in doubts_chat: {e}", exc_info=True)
        return DoubtChatResponse(
            response="Sorry, I'm having trouble understanding. Could you rephrase? 🤔"
        )
# ---------------------------------------------------------------------------
"""


# ---------------------------------------------------------------------------
# Demo / smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("RAG Service — demo run")
    print("=" * 60)

    # --- Ingest sample docs if a folder is passed ---
    if len(sys.argv) > 1:
        folder = sys.argv[1]
        print(f"\n[1] Ingesting documents from: {folder}")
        summary = ingest_folder(folder)
        print(f"    Result: {summary}")

    # --- Smoke-test retrieval + generation ---
    print("\n[2] Running smoke-test retrieval…")
    test_query = "What is the time complexity of binary search and when should I use it?"
    chunks = retrieve_context(
        query=test_query,
        topic="searching",
        top_k=3,
    )
    print(f"    Retrieved {len(chunks)} chunks")
    for i, c in enumerate(chunks, 1):
        print(f"    [{i}] similarity={c.get('similarity', 0):.3f}  topic={c.get('topic')}  excerpt={c.get('content', '')[:80]}…")

    print("\n[3] Generating RAG answer…")
    result = answer_with_rag(
        query=test_query,
        user_context={
            "user_id": None,
            "weak_topics": ["binary search", "searching"],
            "readiness_score": 65,
            "learning_goal": "Google SWE L4",
        },
    )

    print("\n===== RAG RESULT =====")
    print(f"rag_used   : {result['rag_used']}")
    print(f"confidence : {result['confidence']}")
    print(f"section    : {result['section']}")
    print(f"difficulty : {result['difficulty_level']}")
    print(f"sources    : {[s['source'] for s in result['sources']]}")
    print(f"\nresponse:\n{result['response']}")
    print(f"\nsuggestions: {result['suggestions']}")
    print("\n===== EXPECTED OUTPUT SHAPE =====")
    print("""{
  "response": "<grounded explanation from knowledge base>",
  "section": "rag_answer",
  "practice_question": null,
  "difficulty_level": "intermediate",
  "suggestions": ["Ask me to give you a practice problem on searching", ...],
  "sources": [{"source": "docs/searching.md", "topic": "searching", "similarity": 0.82, "excerpt": "..."}],
  "confidence": 0.79,
  "rag_used": true
}""")
