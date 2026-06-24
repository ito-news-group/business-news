"""
pipeline/rag/embed.py
Sorumlu: Harun & Kaan

Görev:
  Bugün scraper'ın çektiği haberleri OpenAI ile embed et,
  pgVector formatında article_embeddings tablosuna yaz.

Çalışma sırası:
  pipeline/run.py tarafından process.py'dan sonra çağrılır.
  (Özet ve sektör bilgisi embed kalitesini artırır)

Girdi:
  Supabase articles tablosu — article_embeddings'de kaydı olmayan haberler

Çıktı:
  article_embeddings tablosuna INSERT:
    - article_id  : int
    - embedding   : vector(1536)   OpenAI text-embedding-3-small
    - chunk_text  : str            embed edilen metin parçası
    - chunk_index : int            uzun metinler bölünürse sıra no

Embedding Modeli:
  OpenAI text-embedding-3-small (1536 boyut, ucuz, hızlı)
  Alternatif: text-embedding-3-large (3072 boyut, daha iyi ama pahalı)

Chunk Stratejisi:
  Kısa haberler (<500 token): tek chunk
  Uzun haberler: 500 token'lık parçalara böl, 50 token overlap
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 500      # token
CHUNK_OVERLAP = 50    # token


def get_unembedded_articles(client) -> list:
    """
    article_embeddings tablosunda kaydı olmayan haberleri getir.
    Sadece bugünküleri değil, tüm geçmiş haberler de olabilir.
    """
    # TODO (Harun & Kaan): Supabase'de LEFT JOIN veya NOT IN ile sorgula
    # Örnek yaklaşım:
    # 1. article_embeddings'deki tüm article_id'leri çek
    # 2. articles'dan bu id'lerde olmayanları filtrele
    raise NotImplementedError("Harun & Kaan implement edecek")


def embed_text(text: str, openai_client) -> list[float]:
    """
    TODO (Harun & Kaan): OpenAI embedding API'sine metin gönder,
    1536 boyutlu vektör döndür.
    """
    # response = openai_client.embeddings.create(
    #     model=EMBEDDING_MODEL,
    #     input=text
    # )
    # return response.data[0].embedding
    raise NotImplementedError("Harun & Kaan implement edecek")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    TODO (Harun & Kaan): Uzun metni chunk'lara böl.
    Basit yaklaşım: kelime bazlı bölme.
    Gelişmiş: tiktoken ile token bazlı bölme.
    """
    # Basit başlangıç: cümle bazlı böl
    raise NotImplementedError("Harun & Kaan implement edecek")


def run_embedding():
    """
    Ana fonksiyon — pipeline/run.py bu fonksiyonu çağırır.
    TODO (Harun & Kaan): embed edilmemiş haberleri al,
    chunk'lara böl, embed et, article_embeddings'e yaz.
    """
    # TODO: OpenAI + Supabase client oluştur
    # TODO: get_unembedded_articles ile haberleri al
    # TODO: Her haber için:
    #   text = f"{article['title']} {article['summary']} {article['full_text']}"
    #   chunks = chunk_text(text)
    #   for i, chunk in enumerate(chunks):
    #       vector = embed_text(chunk, openai_client)
    #       client.table("article_embeddings").insert({
    #           "article_id": article["id"],
    #           "embedding": vector,
    #           "chunk_text": chunk,
    #           "chunk_index": i
    #       }).execute()
    raise NotImplementedError("Harun & Kaan implement edecek")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_embedding()
