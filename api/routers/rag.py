"""
api/routers/rag.py
Sorumlu: Harun & Kaan

Görev:
  Kullanıcının sorularını RAG ile yanıtlar.
  embed.py'ın yazdığı vektörleri kullanarak pgVector'de arama yapar,
  bulunan haberleri GPT-4o-mini'ye context olarak verir, kısa cevap üretir.

Endpoint'ler:
  POST /api/rag/ask     → soru sor, cevap al
  GET  /api/rag/search  → semantik haber arama

Tolunay'a verilecek interface:
  POST /api/rag/ask
    Request:  { "question": "Finans sektöründe bu hafta ne oldu?", "sector": "finans" }
    Response: { "answer": "...", "sources": [12, 34, 56] }
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from api.db import get_supabase
import os

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
GPT_MODEL = "gpt-4o-mini"
TOP_K = 5


class QuestionRequest(BaseModel):
    question: str
    sector: Optional[str] = None
    session_id: Optional[str] = None


class QuestionResponse(BaseModel):
    answer: str
    sources: list[int]
    sector: Optional[str] = None


def embed_question(question: str, openai_client) -> list[float]:
    """
    TODO (Harun & Kaan): Kullanıcı sorusunu embed et.
    embed.py'daki embed_text ile aynı model kullanılmalı.
    """
    raise NotImplementedError("Harun & Kaan implement edecek")


def search_similar_chunks(embedding: list[float], sector: Optional[str], client) -> list[dict]:
    """
    TODO (Harun & Kaan): pgVector'de cosine similarity araması yap.

    Supabase RPC çağrısı:
    result = client.rpc("search_articles", {
        "query_embedding": embedding,
        "sector_filter": sector,
        "match_count": TOP_K
    }).execute()

    Not: search_articles() fonksiyonu db/schema.sql'de tanımlı,
    Supabase'de çalıştırılmış olması gerekiyor.
    """
    raise NotImplementedError("Harun & Kaan implement edecek")


def generate_answer(question: str, chunks: list[dict], openai_client) -> str:
    """
    TODO (Harun & Kaan): Bulunan chunk'ları context olarak kullanarak
    GPT-4o-mini ile kısa cevap üret.

    Prompt örneği:
    Aşağıdaki haberlere dayanarak soruyu 1-2 cümleyle yanıtla.
    Eğer cevap haberlerde yoksa 'Bu konuda bilgim yok' de.
    Haberler: {chunk_texts}
    Soru: {question}
    """
    raise NotImplementedError("Harun & Kaan implement edecek")


@router.post("/ask", response_model=QuestionResponse)
def ask_question(request: QuestionRequest):
    """
    TODO (Harun & Kaan): Bu endpoint'i implement et.

    Adımlar:
    1. OpenAI client oluştur
    2. request.question'ı embed et
    3. pgVector'de search_similar_chunks ile ara
    4. Bulunan chunk'larla generate_answer çağır
    5. QuestionResponse döndür
    """
    return QuestionResponse(
        answer="RAG sistemi henüz implement edilmedi. (Harun & Kaan)",
        sources=[],
        sector=request.sector
    )


@router.get("/search")
def semantic_search(q: str, sector: str = None, limit: int = 5):
    """
    TODO (Harun & Kaan): Semantik haber arama.
    Cevap üretmez, sadece benzer haberleri listeler.

    Dönüş: [{"article_id": 1, "title": "...", "similarity": 0.92}, ...]
    """
    return {
        "query": q,
        "results": [],
        "message": "TODO: Harun & Kaan implement edecek"
    }
