import logging
import math
import os
import re
import time
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.db import get_supabase

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
TOP_K = 5
MAX_RETRIES = 3


class QuestionRequest(BaseModel):
    question: str
    sector: Optional[str] = None
    session_id: Optional[str] = None


class QuestionResponse(BaseModel):
    answer: str
    sources: list[int]
    sector: Optional[str] = None


def embed_question(question: str) -> list[float]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{OLLAMA_BASE_URL}/api/embed",
                    json={"model": OLLAMA_EMBED_MODEL, "input": question},
                )
                response.raise_for_status()
                payload = response.json()
                embedding = payload.get("embeddings") or payload.get("embedding")
                if isinstance(embedding, list):
                    return embedding
                if isinstance(embedding, list) and embedding and isinstance(embedding[0], list):
                    return embedding[0]
                raise HTTPException(status_code=502, detail="Ollama embedding yanıtı beklenen yapıda değil.")
        except httpx.HTTPError as e:
            wait = 2 ** (attempt + 1)
            logger.warning(f"Ollama embedding hatası, yeniden deneniyor ({attempt + 1}/{MAX_RETRIES}): {e}")
            time.sleep(wait)
            last_error = str(e)
    raise HTTPException(status_code=502, detail=f"Ollama embedding hatası: {last_error}")


def _normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _tokenize(text: Optional[str]) -> list[str]:
    cleaned = _normalize_text(text)
    tokens = [token for token in re.findall(r"[a-zA-Z0-9ğüşıöçĞÜŞİÖÇ]+", cleaned) if len(token) > 2]
    normalized = []
    for token in tokens:
        lowered = token.lower()
        normalized.append(lowered)
        if lowered.endswith("leri") and len(lowered) > 5:
            normalized.append(lowered[:-2])
        if lowered.endswith("lar") and len(lowered) > 5:
            normalized.append(lowered[:-2])
        if lowered.endswith("ler") and len(lowered) > 5:
            normalized.append(lowered[:-2])
    return normalized


def _score_article(question: str, article: dict) -> float:
    question_tokens = set(_tokenize(question))
    if not question_tokens:
        return 0.0

    text_parts = [article.get("title"), article.get("summary"), article.get("full_text")]
    text = " ".join(part for part in text_parts if part)
    tokens = set(_tokenize(text))
    if not tokens:
        return 0.0

    question_terms = _tokenize(question)
    title_tokens = set(_tokenize(article.get("title")))
    summary_tokens = set(_tokenize(article.get("summary")))
    full_text_tokens = set(_tokenize(article.get("full_text")))

    overlap = len(question_tokens & tokens)
    title_overlap = len(question_tokens & title_tokens)
    summary_overlap = len(question_tokens & summary_tokens)
    full_text_overlap = len(question_tokens & full_text_tokens)
    if overlap == 0:
        return 0.0

    title_bonus = 1.5 if title_overlap > 0 else 0.0
    summary_bonus = 0.7 if summary_overlap > 0 else 0.0
    full_text_bonus = 0.3 if full_text_overlap > 0 else 0.0
    exact_phrase_bonus = 0.5 if any(term in _normalize_text(article.get("title")) for term in question_terms) else 0.0
    length_penalty = 0.05 * max(0, len(question_tokens) - overlap)
    return overlap + title_bonus + summary_bonus + full_text_bonus + exact_phrase_bonus - length_penalty


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if not norm_a or not norm_b:
        return 0.0

    return dot / (norm_a * norm_b)


def _fallback_search_similar_chunks(embedding: list[float], sector: Optional[str], client) -> list[dict]:
    try:
        article_rows = client.table("articles").select("id, sector").execute()
        article_map = {row["id"]: row.get("sector") for row in article_rows.data or []}

        embedding_rows = client.table("article_embeddings").select("article_id, chunk_text, embedding").execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Yedek arama için veri alınamadı: {str(e)}")

    matches = []
    for row in embedding_rows.data or []:
        article_id = row.get("article_id")
        if article_id is None:
            continue

        article_sector = article_map.get(article_id)
        if sector and article_sector != sector:
            continue

        stored_embedding = row.get("embedding")
        similarity = _cosine_similarity(embedding, stored_embedding) if stored_embedding else 0.0
        if similarity <= 0:
            continue

        matches.append(
            {
                "article_id": article_id,
                "chunk_text": row.get("chunk_text"),
                "similarity": similarity,
            }
        )

    matches.sort(key=lambda item: item["similarity"], reverse=True)
    return matches[:TOP_K]


def search_similar_chunks(query, sector: Optional[str], client) -> list[dict]:
    if isinstance(query, str):
        try:
            # RAG araması, kullanıcı sorusuna göre benzer haberleri Supabase'teki articles tablosundan çeker.
            articles = (
                client.table("articles")
                .select("id, title, summary, full_text, sector")
                .execute()
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Haberler alınamadı: {str(e)}")

        matches = []
        for article in articles.data or []:
            article_sector = article.get("sector")
            if sector and article_sector != sector:
                continue

            score = _score_article(query, article)
            if score <= 0:
                continue

            matches.append(
                {
                    "article_id": article["id"],
                    "chunk_text": article.get("title") or article.get("summary") or "",
                    "similarity": round(score, 4),
                }
            )

        matches.sort(key=lambda item: item["similarity"], reverse=True)
        if matches:
            return matches[:TOP_K]

        if sector:
            return search_similar_chunks(query, None, client)

        return []

    try:
        result = client.rpc(
            "search_articles",
            {
                "query_embedding": query,
                "sector_filter": sector,
                "match_count": TOP_K,
            },
        ).execute()

        if result.data:
            return result.data

        if sector:
            fallback = client.rpc(
                "search_articles",
                {
                    "query_embedding": query,
                    "sector_filter": None,
                    "match_count": TOP_K,
                },
            ).execute()
            if fallback.data:
                return fallback.data

        return []
    except Exception as e:
        error_text = str(e).lower()
        if "function" in error_text and "not found" in error_text:
            raise HTTPException(
                status_code=500,
                detail="search_articles() RPC fonksiyonu Supabase'de tanımlı değil. db/schema.sql'den çalıştırın.",
            )
        if "different vector dimensions" in error_text or "vector dimensions" in error_text:
            logger.warning("pgvector boyut uyuşmazlığı tespit edildi, yedek python araması kullanılacak.")
            return _fallback_search_similar_chunks(query, sector, client)
        raise HTTPException(status_code=500, detail=f"pgVector arama hatası: {str(e)}")


def _build_local_answer(question: str, chunks: list[dict], article_map: dict) -> str:
    if not chunks:
        return "Bu konuda bilgim yok."

    snippets = []
    for chunk in chunks[:3]:
        article = article_map.get(chunk["article_id"])
        title = (article or {}).get("title") or ""
        summary = (article or {}).get("summary") or ""

        if title and summary:
            clean_summary = re.sub(r"\s+", " ", summary).strip()
            snippets.append(f"- {title}: {clean_summary[:220]}")
        elif title:
            snippets.append(f"- {title}")
        elif chunk.get("chunk_text"):
            snippets.append(f"- {chunk['chunk_text'][:220]}")

    if snippets:
        return "Benzer haberlerden özet:\n" + "\n".join(snippets)

    return f"Bu konuda benzer haberler bulundu: {chunks[0]['chunk_text']}"


def generate_answer(question: str, chunks: list[dict], client) -> str:
    try:
        article_ids = [chunk["article_id"] for chunk in chunks[:3]]
        # Cevap oluşturmak için seçilen makalelerin başlık ve özet bilgileri yine articles tablosundan çekilir.
        articles = (
            client.table("articles")
            .select("id, title, summary")
            .in_("id", article_ids)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Article detayları alınamadı, yerel cevap kullanılıyor: {e}")
        articles = None

    article_map = {article["id"]: article for article in (articles.data or []) if article.get("id")}
    if not article_map and chunks:
        article_ids = [chunk["article_id"] for chunk in chunks[:3]]
        try:
            fallback_articles = (
                client.table("articles")
                .select("id, title, summary")
                .in_("id", article_ids)
                .execute()
            )
            article_map = {article["id"]: article for article in (fallback_articles.data or []) if article.get("id")}
        except Exception:
            article_map = {}
    answer = _build_local_answer(question, chunks, article_map)
    if answer and "Bu konuda bilgim yok" not in answer:
        return answer

    return answer


@router.post("/ask", response_model=QuestionResponse)
def ask_question(request: QuestionRequest):
    client = get_supabase()

    try:
        chunks = search_similar_chunks(request.question, request.sector, client)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama sırasında hata: {str(e)}")

    if not chunks:
        return QuestionResponse(
            answer="Bu konuda bilgim yok (benzer haber bulunamadı).",
            sources=[],
            sector=request.sector,
        )

    try:
        answer = generate_answer(request.question, chunks, client)
    except Exception:
        answer = "Cevap üretilemedi, lütfen tekrar deneyin."

    source_ids = list(dict.fromkeys(c["article_id"] for c in chunks))

    try:
        client.table("chat_sessions").insert(
            {
                "question": request.question,
                "answer": answer,
                "sources": source_ids,
                "sector_filter": request.sector,
            }
        ).execute()
    except Exception as e:
        logger.error(f"Sohbet kaydı yazılamadı: {e}")

    return QuestionResponse(
        answer=answer,
        sources=source_ids,
        sector=request.sector,
    )


@router.get("/search")
def semantic_search(q: str, sector: str = None, limit: int = 5):
    client = get_supabase()

    try:
        result_data = search_similar_chunks(q, sector, client)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama hatası: {str(e)}")

    article_ids = [r["article_id"] for r in result_data]
    if not article_ids:
        return {"query": q, "results": []}

    try:
        articles = (
            client.table("articles")
            .select("id, title, summary, sector, published_at")
            .in_("id", article_ids)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Haber detayları alınamadı: {str(e)}")

    article_map = {a["id"]: a for a in articles.data}
    results = []
    for r in result_data:
        a = article_map.get(r["article_id"])
        if a:
            results.append(
                {
                    "article_id": r["article_id"],
                    "title": a["title"],
                    "sector": a["sector"],
                    "summary": a["summary"],
                    "similarity": round(r["similarity"], 4),
                }
            )

    return {"query": q, "results": results}

