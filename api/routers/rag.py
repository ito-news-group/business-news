import asyncio
import logging
import os
import time
from functools import partial
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.db import get_supabase
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

router = APIRouter()

EMBED_MODEL = "BAAI/bge-m3"
TOP_K = 5
FETCH_MULTIPLIER = 3
SEARCH_RPC = "search_articles"
MIN_SIMILARITY = 0.5
USE_RERANKER = True
USE_HYBRID = True
RERANKER_TOP_K = 3
QUERY_CACHE_TTL = 5.0
USE_LLM = True

_embedder = None
_reranker = None
_query_cache: dict[str, float] = {}


def get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(
            EMBED_MODEL,
            token=os.getenv("HF_TOKEN") or None,
        )
        dim = _embedder.get_embedding_dimension()
        logger.info(f"Embedder loaded: {EMBED_MODEL} ({dim}-dim)")
    except Exception as e:
        logger.error(f"Embedder yuklenemedi: {e}")
        raise
    return _embedder


def get_reranker():
    global _reranker
    if _reranker is not None:
        return _reranker
    if not USE_RERANKER:
        return None
    try:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder("seroe/bge-reranker-v2-m3-turkish-triplet")
        logger.info("Reranker loaded")
        return _reranker
    except Exception as e:
        logger.warning(f"Reranker yuklenemedi: {e}")
        return None


def validate_query(q: str) -> str:
    q = q.strip()
    if len(q) < 3:
        raise HTTPException(400, "Sorgu en az 3 karakter olmali")
    if len(q) > 500:
        raise HTTPException(400, "Sorgu cok uzun (max 500 karakter)")
    gibberish = sum(1 for c in q if c.isalnum() or c.isspace()) / max(len(q), 1)
    if gibberish < 0.3:
        raise HTTPException(400, "Gecersiz sorgu formati")
    return q


def check_query_dedup(q: str):
    key = q.lower().strip()
    now = time.time()
    if key in _query_cache and now - _query_cache[key] < QUERY_CACHE_TTL:
        raise HTTPException(429, "Bu sorgu cok yakin zamanda soruldu, lutfen bekleyin")
    _query_cache[key] = now


class AskRequest(BaseModel):
    question: str
    sector: Optional[str] = None


class ChunkResult(BaseModel):
    article_id: int
    chunk_text: str
    parent_text: Optional[str] = None
    similarity: float
    title: Optional[str] = None
    url: Optional[str] = None


class AskResponse(BaseModel):
    query: str
    results: list[ChunkResult]
    total: int
    answer: str = ""


async def embed_query(text: str):
    embedder = get_embedder()
    loop = asyncio.get_event_loop()
    try:
        vector = await loop.run_in_executor(None, embedder.encode, text)
        return vector.tolist()
    except Exception as e:
        logger.error(f"Query embedding hatasi: {e}")
        raise HTTPException(status_code=502, detail=f"Embedding hatasi: {str(e)}")


def search_chunks(embedding: list[float], limit: int, client, sector_filter: Optional[str] = None):
    try:
        result = client.rpc(SEARCH_RPC, {
            "query_embedding": embedding,
            "sector_filter": sector_filter,
            "match_count": limit,
        }).execute()
        return result.data
    except Exception as e:
        logger.error(f"pgVector arama hatasi: {e}")
        if "function" in str(e).lower():
            raise HTTPException(
                status_code=500,
                detail=f"{SEARCH_RPC}() fonksiyonu tanimli degil. Supabase SQL Editor'den migration'i calistirin."
            )
        raise HTTPException(status_code=500, detail=f"Arama hatasi: {str(e)}")


def deduplicate_by_article(chunks: list[dict]) -> list[dict]:
    seen = {}
    for c in chunks:
        aid = c["article_id"]
        if aid not in seen or c["similarity"] > seen[aid]["similarity"]:
            seen[aid] = c
    return list(seen.values())


def filter_by_threshold(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if c["similarity"] >= MIN_SIMILARITY]


def rerank_results(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    reranker = get_reranker()
    if reranker is None:
        return chunks[:top_k]
    try:
        pairs = [(query, c["chunk_text"]) for c in chunks]
        scores = reranker.predict(pairs)
        scored = list(zip(chunks, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {**c, "rerank_score": float(s)} for c, s in scored[:top_k]
        ]
    except Exception as e:
        logger.error(f"Reranking sirasinda hata: {e}")
        return chunks[:top_k]


def enrich_with_article_info(chunks: list[dict], client) -> list[dict]:
    article_ids = list(dict.fromkeys(c["article_id"] for c in chunks))
    if not article_ids:
        return chunks
    try:
        articles = (
            client.table("articles")
            .select("id, title, summary, url")
            .in_("id", article_ids)
            .execute()
        )
        article_map = {a["id"]: a for a in articles.data}
        for c in chunks:
            info = article_map.get(c["article_id"])
            c["title"] = info["title"] if info else None
            c["url"] = info["url"] if info else None
        return chunks
    except Exception as e:
        logger.warning(f"Article bilgisi alinamadi: {e}")
        return chunks


def fulltext_search(query: str, limit: int, client):
    try:
        clean_q = query.strip().replace("'", "''")
        if not clean_q:
            return []
        like = f"%{clean_q}%"
        result = (
            client.table("articles")
            .select("id, title, url")
            .or_(f"title.ilike.{like},summary.ilike.{like},full_text.ilike.{like}")
            .limit(limit)
            .execute()
        )
        return result.data
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


@router.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    client = get_supabase()
    loop = asyncio.get_event_loop()

    request.question = validate_query(request.question)
    check_query_dedup(request.question)

    try:
        embedding = await embed_query(request.question)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Soru islenirken hata: {str(e)}")

    fetch_k = TOP_K * FETCH_MULTIPLIER
    try:
        raw_chunks = await loop.run_in_executor(
            None, partial(search_chunks, embedding, fetch_k, client, sector_filter=request.sector)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama sirasinda hata: {str(e)}")

    if not raw_chunks:
        return AskResponse(
            query=request.question,
            results=[],
            total=0,
        )

    unique_chunks = deduplicate_by_article(raw_chunks)

    if USE_RERANKER:
        unique_chunks = await loop.run_in_executor(
            None, partial(rerank_results, request.question, unique_chunks, RERANKER_TOP_K)
        )

    result_k = RERANKER_TOP_K if USE_RERANKER else TOP_K
    unique_chunks = unique_chunks[:result_k]
    filtered = filter_by_threshold(unique_chunks)
    enriched = enrich_with_article_info(filtered, client)

    results = [
        ChunkResult(
            article_id=c["article_id"],
            chunk_text=c.get("chunk_text", ""),
            parent_text=c.get("parent_text"),
            similarity=round(c.get("similarity", 0), 4),
            title=c.get("title"),
            url=c.get("url"),
        )
        for c in enriched
    ]

    try:
        source_ids = [c["article_id"] for c in enriched]
        client.table("chat_sessions").insert({
            "question": request.question,
            "sources": source_ids,
        }).execute()
    except Exception as e:
        logger.error(f"Sohbet kaydi yazilamadi: {e}")

    answer = ""
    if USE_LLM and enriched:
        try:
            from pipeline.rag.llm_providers import get_llm_provider, SYSTEM_PROMPT
            provider = get_llm_provider()
            if provider:
                context = "\n\n".join(
                    f"[{i+1}] {r.get('title', '')}\n{r.get('chunk_text', '')}"
                    for i, r in enumerate(enriched)
                )
                user_prompt = f"BAĞLAM:\n{context}\n\nSORU: {request.question}"
                answer = provider.generate(SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.error(f"LLM cevap üretilemedi: {e}")

    return AskResponse(
        query=request.question,
        results=results,
        total=len(results),
        answer=answer,
    )


@router.get("/search")
async def semantic_search(q: str, limit: int = 5, hybrid: Optional[bool] = None):
    client = get_supabase()
    loop = asyncio.get_event_loop()
    use_hybrid = USE_HYBRID if hybrid is None else hybrid

    q = validate_query(q)

    try:
        embedding = await embed_query(q)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Soru embed edilirken hata: {str(e)}")

    fetch_k = limit * FETCH_MULTIPLIER
    try:
        raw_chunks = await loop.run_in_executor(
            None, partial(search_chunks, embedding, fetch_k, client)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama hatasi: {str(e)}")

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
                "title": c.get("title"),
                "url": c.get("url"),
            }
            for c in results
        ],
    }
