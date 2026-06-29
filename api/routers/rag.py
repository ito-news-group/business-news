import asyncio
import logging
import os
import re
import time
from collections import deque
from functools import partial
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

from api.db import get_supabase
from dotenv import load_dotenv

from pipeline.rag.reranker import CohereReranker
from pipeline.rag.llm_providers import get_llm_provider, SYSTEM_PROMPT

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

router = APIRouter()

EMBED_MODEL = "jina-embeddings-v3"
EMBED_DIM = 1024
EMBED_QUERY_TASK = "retrieval.query"
TOP_K = 5
FETCH_MULTIPLIER = 3
SEARCH_RPC = "search_articles"
MIN_SIMILARITY = 0.35
USE_RERANKER = True
RERANKER_TOP_K = 3
USE_HYBRID = True
USE_LLM = True
CONTEXT_TOKEN_BUDGET = 1500

_jina_client = None
_reranker: Optional[CohereReranker] = None
_query_cache: dict[str, float] = {}
QUERY_CACHE_TTL = 4.0
_pg_pool = None


def _get_pg():
    global _pg_pool
    if _pg_pool is None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise HTTPException(500, "DATABASE_URL tanimli degil")
        try:
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn)
        except Exception as e:
            logger.error(f"DB pool acilamadi: {e}")
            raise HTTPException(500, f"Veritabanina baglanilamadi: {e}")
    return _pg_pool


# ---------- Embedding (Jina API) ----------

def _get_jina():
    global _jina_client
    if _jina_client is not None:
        return _jina_client
    api_key = os.getenv("JINA_API_KEY")
    if not api_key:
        raise HTTPException(500, "JINA_API_KEY tanimli degil")
    try:
        from openai import OpenAI
        _jina_client = OpenAI(
            base_url="https://api.jina.ai/v1",
            api_key=api_key,
        )
        logger.info(f"Jina query embedder hazir: {EMBED_MODEL} ({EMBED_DIM}-dim)")
    except Exception as e:
        logger.error(f"Jina client acilamadi: {e}")
        raise HTTPException(500, f"Embedding client hatasi: {e}")
    return _jina_client


def embed_query_sync(text: str) -> list[float]:
    client = _get_jina()
    try:
        resp = client.embeddings.create(
            model=EMBED_MODEL,
            input=[text],
            encoding_format="float",
            dimensions=EMBED_DIM,
            extra_body={"task": EMBED_QUERY_TASK},
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.error(f"Query embedding hatasi: {e}")
        raise


async def embed_query(text: str) -> list[float]:
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, embed_query_sync, text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Soru embed edilemedi: {e}")


# ---------- Reranker (Cohere) ----------

def get_reranker() -> Optional[CohereReranker]:
    global _reranker
    if _reranker is not None:
        return _reranker
    if not USE_RERANKER or not os.getenv("COHERE_API_KEY"):
        logger.info("Cohere reranker kapali (COHERE_API_KEY yok veya USE_RERANKER=false)")
        return None
    try:
        _reranker = CohereReranker(top_k=RERANKER_TOP_K)
        logger.info("Cohere reranker hazir")
    except Exception as e:
        logger.warning(f"Reranker olusturulamadi: {e}")
        _reranker = None
    return _reranker


# ---------- Validation & dedup ----------

ALLOWED_RE = re.compile(r"^[A-Za-zÇĞİÖŞÜçğıöşü0-9\s\.\,\?\!\:\;\-\"'\(\)%]+$")


def validate_query(q: str) -> str:
    q = q.strip()
    if len(q) < 3:
        raise HTTPException(400, "Sorgu en az 3 karakter olmali")
    if len(q) > 500:
        raise HTTPException(400, "Sorgu cok uzun (max 500 karakter)")
    if not ALLOWED_RE.match(q):
        raise HTTPException(400, "Gecersiz karakter(ler) tespit edildi")
    return q


def check_query_dedup(q: str):
    key = q.lower().strip()
    now = time.time()
    if key in _query_cache and now - _query_cache[key] < QUERY_CACHE_TTL:
        raise HTTPException(429, "Ayni sorgu cok yakin zamanda soruldu, lutfen bekleyin")
    _query_cache[key] = now
    # cache'i 60 sn'de bir temizle
    stale = [k for k, t in _query_cache.items() if now - t > 60]
    for k in stale:
        _query_cache.pop(k, None)


# ---------- Auth (internal API key) ----------

async def require_api_key(x_api_key: Optional[str] = Header(None)):
    expected = os.getenv("API_KEY")
    if not expected:
        return  # dev modda kapat
    if not x_api_key or x_api_key != expected:
        raise HTTPException(401, "Gecersiz API key")
    return x_api_key


# ---------- Rate limit (simple in-memory) ----------

RATE_LIMIT = 15  # istek/dakika/IP
_rate_state: dict[str, list[float]] = {}

# ---------- Metrics ----------

_metrics_window = deque(maxlen=200)

def _record_metric(stage: str, ms: float, status: str, chunks: int = 0):
    """istek basina metrik kaydet (thread-safe değil ama single-worker'da sorunsuz)"""
    _metrics_window.append({
        "ts": time.time(),
        "stage": stage,
        "ms": round(ms, 1),
        "status": status,
        "chunks": chunks,
    })


def check_rate_limit(client_ip: str):
    now = time.time()
    window = 60.0
    hits = _rate_state.get(client_ip, [])
    hits = [t for t in hits if now - t < window]
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(429, f"Cok fazla istek (max {RATE_LIMIT}/dk)")
    hits.append(now)
    _rate_state[client_ip] = hits


# ---------- Token counting ----------

def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def trim_context(chunks: list[dict], budget: int = CONTEXT_TOKEN_BUDGET) -> list[dict]:
    trimmed = []
    used = 0
    for c in chunks:
        text = c.get("parent_text") or c.get("chunk_text", "")
        t = _count_tokens(text)
        if used + t > budget:
            break
        trimmed.append(c)
        used += t
    return trimmed


# ---------- Search ----------

def search_chunks(embedding: list[float], limit: int, client, sector_filter: Optional[str] = None):
    try:
        pool = _get_pg()
        conn = pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            cur.execute(
                """SELECT ae.article_id, ae.chunk_text, ae.parent_text, ae.chunk_index,
                    1 - (ae.embedding <=> %s::vector) AS similarity
                FROM article_embeddings ae
                JOIN articles a ON a.id = ae.article_id
                WHERE (%s::text IS NULL OR a.sector = %s)
                ORDER BY ae.embedding <=> %s::vector
                LIMIT %s""",
                (embedding_str, sector_filter, sector_filter, embedding_str, limit),
            )
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        finally:
            pool.putconn(conn)
    except Exception as e:
        logger.error(f"pgVector arama hatasi: {e}")
        raise HTTPException(500, f"Arama hatasi: {e}")


def deduplicate_by_article(chunks: list[dict]) -> list[dict]:
    seen = {}
    for c in chunks:
        aid = c["article_id"]
        if aid not in seen or c["similarity"] > seen[aid]["similarity"]:
            seen[aid] = c
    return list(seen.values())


def filter_by_threshold(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if (c.get("similarity") or 0) >= MIN_SIMILARITY]


def rerank_results(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    reranker = get_reranker()
    if reranker is None:
        return chunks[:top_k]
    try:
        return reranker.rerank(query, chunks, top_k=top_k)
    except Exception as e:
        logger.error(f"Rerank hatasi: {e}")
        return chunks[:top_k]


def enrich_with_article_info(chunks: list[dict], client) -> list[dict]:
    article_ids = list(dict.fromkeys(c["article_id"] for c in chunks))
    if not article_ids:
        return chunks
    try:
        pool = _get_pg()
        conn = pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT id, title, summary, url FROM articles WHERE id = ANY(%s)",
                (article_ids,),
            )
            article_map = {a["id"]: a for a in cur.fetchall()}
            cur.close()
            for c in chunks:
                info = article_map.get(c["article_id"])
                c["title"] = info["title"] if info else None
                c["url"] = info["url"] if info else None
            return chunks
        finally:
            pool.putconn(conn)
    except Exception as e:
        logger.warning(f"Article bilgisi alinamadi: {e}")
        return chunks


def fulltext_search(query: str, limit: int, client):
    clean_q = query.strip()
    if not clean_q:
        return []
    try:
        pool = _get_pg()
        conn = pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT a.id, a.title, a.url,
                     ts_rank(a.tsv, plainto_tsquery('turkish', %s)) AS rank
                FROM articles a
                WHERE a.tsv @@ plainto_tsquery('turkish', %s)
                ORDER BY rank DESC
                LIMIT %s""",
                (clean_q, clean_q, limit),
            )
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        finally:
            pool.putconn(conn)
    except Exception as e:
        logger.warning(f"Full-text search hatasi: {e}")
        return []


def rrf_merge(vector_results: list[dict], fts_results: list[dict], k: int = 60) -> list[dict]:
    scores = {}
    for rank, item in enumerate(vector_results):
        aid = item["article_id"]
        scores.setdefault(aid, {
            "article_id": aid,
            "chunk_text": item.get("chunk_text", ""),
            "parent_text": item.get("parent_text"),
            "similarity": 0,
        })
        scores[aid]["rrf_score"] = scores[aid].get("rrf_score", 0) + 1 / (k + rank + 1)
        if item.get("similarity", 0) > scores[aid]["similarity"]:
            scores[aid]["similarity"] = item["similarity"]
            scores[aid]["chunk_text"] = item.get("chunk_text", scores[aid]["chunk_text"])
            scores[aid]["parent_text"] = item.get("parent_text", scores[aid]["parent_text"])

    for rank, item in enumerate(fts_results):
        aid = item["id"]
        scores.setdefault(aid, {
            "article_id": aid,
            "chunk_text": item.get("title", ""),
            "parent_text": None,
            "similarity": 0,
        })
        scores[aid]["rrf_score"] = scores[aid].get("rrf_score", 0) + 1 / (k + rank + 1)

    sorted_items = sorted(scores.values(), key=lambda x: x["rrf_score"], reverse=True)
    return sorted_items


# ---------- Models ----------

class AskRequest(BaseModel):
    question: str
    sector: Optional[str] = None
    session_id: Optional[str] = None


class ChunkResult(BaseModel):
    article_id: int
    chunk_text: str
    parent_text: Optional[str] = None
    similarity: float
    rerank_score: Optional[float] = None
    title: Optional[str] = None
    url: Optional[str] = None


class AskResponse(BaseModel):
    query: str
    results: list[ChunkResult]
    total: int
    answer: str = ""


# ---------- Pipeline (shared retrieval) ----------

async def retrieve(request: AskRequest, client, loop) -> list[dict]:
    try:
        t0 = time.time()
        embedding = await embed_query(request.question)
        _record_metric("embed", (time.time() - t0) * 1000, "ok")

        t0 = time.time()
        fetch_k = TOP_K * FETCH_MULTIPLIER
        raw_chunks = await loop.run_in_executor(
            None, partial(search_chunks, embedding, fetch_k, client, request.sector)
        )
        _record_metric("search", (time.time() - t0) * 1000, "ok", len(raw_chunks))

        if not raw_chunks:
            return []
        unique_chunks = deduplicate_by_article(raw_chunks)

        if USE_HYBRID:
            fts_results = await loop.run_in_executor(
                None, partial(fulltext_search, request.question, fetch_k, client)
            )
            if fts_results:
                unique_chunks = rrf_merge(unique_chunks, fts_results)

        if USE_RERANKER:
            t0 = time.time()
            unique_chunks = await loop.run_in_executor(
                None, partial(rerank_results, request.question, unique_chunks, RERANKER_TOP_K)
            )
            _record_metric("rerank", (time.time() - t0) * 1000, "ok")

        result_k = RERANKER_TOP_K if USE_RERANKER else TOP_K
        unique_chunks = unique_chunks[:result_k]
        filtered = filter_by_threshold(unique_chunks)
        enriched = enrich_with_article_info(filtered, client)
        return enriched
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"retrieve beklenmeyen hata: {e}", exc_info=True)
        raise HTTPException(500, f"Arama sirasinda hata: {e}")


def save_chat_session(client, question: str, answer: str, enriched: list[dict], sector: Optional[str], session_id: Optional[str]):
    try:
        client.table("chat_sessions").insert({
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "sources": [c["article_id"] for c in enriched],
            "sector_filter": sector,
        }).execute()
    except Exception as e:
        logger.error(f"Sohbet kaydi yazilamadi: {e}")


def build_context_prompt(question: str, enriched: list[dict]) -> str:
    context_parts = []
    for i, r in enumerate(enriched, 1):
        title = r.get("title", "")
        body = r.get("parent_text") or r.get("chunk_text", "")
        context_parts.append(f"[{i}] {title}\n{body}")
    context = "\n\n".join(context_parts)
    return (
        f"Asagidaki haberleri kullanarak soruya cevap ver. "
        f"SADECE bu haberlerde yazan bilgileri kullan, kendi bilgini ekleme. "
        f"Cevap haberlerde yoksa 'Bu soruya haberlerimizde cevap bulamadim' de.\n\n"
        f"--- HABER METINLERI ---\n{context}\n--- HABER SONU ---\n\n"
        f"SORU: {question}\n\n"
        f"CEVAP (sadece yukaridaki haberlere dayanarak, 1-2 cumle):"
    )


# ---------- Endpoints ----------

@router.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
async def ask_question(request: AskRequest, req: Request):
    try:
        t_start = time.time()
        client = get_supabase()
        loop = asyncio.get_event_loop()

        request.question = validate_query(request.question)
        check_query_dedup(request.question)
        check_rate_limit(req.client.host if req.client else "unknown")

        t0 = time.time()
        enriched = await retrieve(request, client, loop)
        _record_metric("total", (time.time() - t0) * 1000, "ok" if enriched else "empty", len(enriched))

        if not enriched:
            return AskResponse(query=request.question, results=[], total=0)

        trimmed = trim_context(enriched)
        user_prompt = build_context_prompt(request.question, trimmed)

        answer = ""
        if USE_LLM and trimmed:
            t_llm = time.time()
            try:
                provider = get_llm_provider()
                answer = provider.generate(SYSTEM_PROMPT, user_prompt)
                _record_metric("llm", (time.time() - t_llm) * 1000, "ok")
            except Exception as e:
                logger.error(f"LLM cevap üretilemedi: {e}")
                _record_metric("llm", (time.time() - t_llm) * 1000, "fail")

        save_chat_session(client, request.question, answer, trimmed, request.sector, request.session_id)

        results = [
            ChunkResult(
                article_id=c["article_id"],
                chunk_text=c.get("chunk_text", ""),
                parent_text=c.get("parent_text"),
                similarity=round(c.get("similarity", 0), 4),
                rerank_score=round(v, 4) if (v := c.get("rerank_score")) else None,
                title=c.get("title"),
                url=c.get("url"),
            )
            for c in trimmed
        ]
        return AskResponse(query=request.question, results=results, total=len(results), answer=answer)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ask_question beklenmeyen hata: {e}", exc_info=True)
        raise HTTPException(500, f"Istek islenirken hata: {e}")


@router.get("/search", dependencies=[Depends(require_api_key)])
async def semantic_search(q: str, limit: int = 5, hybrid: Optional[bool] = None, req: Request = None):
    try:
        client = get_supabase()
        loop = asyncio.get_event_loop()
        use_hybrid = USE_HYBRID if hybrid is None else hybrid

        q = validate_query(q)
        check_rate_limit(req.client.host if req and req.client else "unknown")

        embedding = await embed_query(q)
        fetch_k = limit * FETCH_MULTIPLIER
        raw_chunks = await loop.run_in_executor(
            None, partial(search_chunks, embedding, fetch_k, client)
        )

        unique_chunks = deduplicate_by_article(raw_chunks)

        if use_hybrid:
            fts_results = await loop.run_in_executor(
                None, partial(fulltext_search, q, fetch_k, client)
            )
            merged = rrf_merge(unique_chunks, fts_results)
            merged = filter_by_threshold(merged)
            merged = enrich_with_article_info(merged, client)
            results = merged[:limit]
        else:
            trimmed = unique_chunks[:limit]
            filtered = filter_by_threshold(trimmed)
            enriched = enrich_with_article_info(filtered, client)
            results = enriched

        return {
            "query": q,
            "results": [
                {
                    "article_id": c["article_id"],
                    "chunk_text": c.get("chunk_text", ""),
                    "parent_text": c.get("parent_text"),
                    "similarity": round(c.get("similarity", 0), 4),
                    "rerank_score": round(v, 4) if (v := c.get("rerank_score")) else None,
                    "title": c.get("title"),
                    "url": c.get("url"),
                }
                for c in results
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"semantic_search beklenmeyen hata: {e}", exc_info=True)
        raise HTTPException(500, f"Arama sirasinda hata: {e}")


@router.get("/metrics")
async def rag_metrics():
    now = time.time()
    window_60 = [m for m in _metrics_window if now - m["ts"] < 60]
    window_300 = [m for m in _metrics_window if now - m["ts"] < 300]

    all_stages = [m for m in window_60 if m["stage"] == "total"]
    errors = [m for m in window_60 if m["status"] != "ok"]
    embed_stages = [m for m in window_60 if m["stage"] == "embed"]
    search_stages = [m for m in window_60 if m["stage"] == "search"]
    llm_stages = [m for m in window_60 if m["stage"] == "llm"]
    rerank_stages = [m for m in window_60 if m["stage"] == "rerank"]

    def avg(lst, key="ms"):
        return round(sum(m[key] for m in lst) / max(len(lst), 1), 1)

    def p95(lst, key="ms"):
        if not lst:
            return 0
        s = sorted(m[key] for m in lst)
        return s[int(len(s) * 0.95)]

    total_chunks = sum(m.get("chunks", 0) for m in all_stages)

    return {
        "window_60s": {
            "requests": len(all_stages),
            "errors": len(errors),
            "chunks_retrieved": total_chunks,
            "avg_latency_ms": avg(all_stages),
            "p95_latency_ms": p95(all_stages),
            "stages": {
                "embed": {"count": len(embed_stages), "avg_ms": avg(embed_stages)},
                "search": {"count": len(search_stages), "avg_ms": avg(search_stages)},
                "rerank": {"count": len(rerank_stages), "avg_ms": avg(rerank_stages)},
                "llm": {"count": len(llm_stages), "avg_ms": avg(llm_stages)},
            },
        },
        "window_300s": {
            "requests": len(window_300),
            "errors": len([m for m in window_300 if m["status"] != "ok"]),
        },
        "cache_entries": len(_query_cache),
        "rate_limited_ips": len(_rate_state),
    }


@router.get("/metrics/db")
async def rag_metrics_db():
    import psycopg2
    import os as _os
    dsn = _os.getenv("DATABASE_URL")
    if not dsn:
        return {"error": "DATABASE_URL yok"}
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM article_embeddings")
        chunks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM articles WHERE full_text IS NOT NULL AND length(full_text) >= 300")
        articles = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT ae.article_id) FROM article_embeddings ae")
        unique = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {
            "chunks": chunks,
            "articles": articles,
            "unique_embedded": unique,
            "coverage": round(unique / max(articles, 1) * 100, 1),
        }
    except Exception as e:
        return {"error": str(e)}