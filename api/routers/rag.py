import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.db import get_supabase
import os
from dotenv import load_dotenv
from openai import OpenAI, APIError, RateLimitError, APITimeoutError

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
GPT_MODEL = "gpt-4o-mini"
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


def embed_question(question: str, openai_client) -> list[float]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=question,
                timeout=30
            )
            return response.data[0].embedding
        except RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning(f"Embedding rate limit, retrying in {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
            last_error = "OpenAI rate limit aşıldı, lütfen tekrar deneyin."
        except APITimeoutError:
            wait = 2 ** attempt
            logger.warning(f"Embedding timeout, retrying in {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
            last_error = "OpenAI bağlantı zaman aşımı."
        except APIError as e:
            raise HTTPException(status_code=502, detail=f"OpenAI API hatası (embedding): {str(e)}")
    raise HTTPException(status_code=429, detail=last_error)


def search_similar_chunks(embedding: list[float], sector: Optional[str], client) -> list[dict]:
    try:
        result = client.rpc("search_articles", {
            "query_embedding": embedding,
            "sector_filter": sector,
            "match_count": TOP_K
        }).execute()
        return result.data
    except Exception as e:
        if "function" in str(e).lower() and "not found" in str(e).lower():
            raise HTTPException(
                status_code=500,
                detail="search_articles() RPC fonksiyonu Supabase'de tanımlı değil. db/schema.sql'den çalıştırın."
            )
        raise HTTPException(status_code=500, detail=f"pgVector arama hatası: {str(e)}")


def generate_answer(question: str, chunks: list[dict], openai_client) -> str:
    chunk_texts = "\n\n".join(
        f"[{i+1}] {c['chunk_text']}" for i, c in enumerate(chunks)
    )

    prompt = f"""Aşağıdaki haberlere dayanarak soruyu 1-2 cümleyle yanıtla.
Eğer cevap haberlerde yoksa 'Bu konuda bilgim yok' de.

Haberler:
{chunk_texts}

Soru: {question}"""

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = openai_client.chat.completions.create(
                model=GPT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
                timeout=30
            )
            return response.choices[0].message.content.strip()
        except RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning(f"GPT rate limit, retrying in {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
            last_error = "OpenAI rate limit aşıldı."
        except APITimeoutError:
            wait = 2 ** attempt
            logger.warning(f"GPT timeout, retrying in {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
            last_error = "OpenAI bağlantı zaman aşımı."
        except APIError as e:
            logger.error(f"GPT API hatası: {e}")
            last_error = f"OpenAI API hatası: {str(e)}"
    return f"Cevap üretilemedi: {last_error}"


@router.post("/ask", response_model=QuestionResponse)
def ask_question(request: QuestionRequest):
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI client oluşturulamadı: {str(e)}")

    client = get_supabase()

    try:
        question_embedding = embed_question(request.question, openai_client)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Soru işlenirken hata: {str(e)}")

    try:
        chunks = search_similar_chunks(question_embedding, request.sector, client)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama sırasında hata: {str(e)}")

    if not chunks:
        return QuestionResponse(
            answer="Bu konuda bilgim yok (benzer haber bulunamadı).",
            sources=[],
            sector=request.sector
        )

    try:
        answer = generate_answer(request.question, chunks, openai_client)
    except Exception as e:
        answer = "Cevap üretilemedi, lütfen tekrar deneyin."

    source_ids = list(dict.fromkeys(c["article_id"] for c in chunks))

    try:
        client.table("chat_sessions").insert({
            "question": request.question,
            "answer": answer,
            "sources": source_ids,
            "sector_filter": request.sector,
        }).execute()
    except Exception as e:
        logger.error(f"Sohbet kaydı yazılamadı: {e}")

    return QuestionResponse(
        answer=answer,
        sources=source_ids,
        sector=request.sector
    )


@router.get("/search")
def semantic_search(q: str, sector: str = None, limit: int = 5):
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI client oluşturulamadı: {str(e)}")

    client = get_supabase()

    try:
        embedding = embed_question(q, openai_client)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Soru embed edilirken hata: {str(e)}")

    try:
        result = client.rpc("search_articles", {
            "query_embedding": embedding,
            "sector_filter": sector,
            "match_count": limit
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Arama hatası: {str(e)}")

    article_ids = [r["article_id"] for r in result.data]
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
    for r in result.data:
        a = article_map.get(r["article_id"])
        if a:
            results.append({
                "article_id": r["article_id"],
                "title": a["title"],
                "sector": a["sector"],
                "summary": a["summary"],
                "similarity": round(r["similarity"], 4),
            })

    return {"query": q, "results": results}
