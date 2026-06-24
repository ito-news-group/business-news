import os
import logging
import time
import tiktoken
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from openai import APIError, RateLimitError, APITimeoutError

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
PAGE_SIZE = 1000
MAX_RETRIES = 3

BATCH_SIZE = 20


def get_unembedded_articles(client) -> list:
    try:
        embedded_ids = client.table("article_embeddings").select("article_id").execute()
        embedded_set = {row["article_id"] for row in embedded_ids.data}
    except Exception as e:
        logger.error(f"Embedding ID'leri alınamadı: {e}")
        raise

    unembedded = []
    offset = 0
    while True:
        try:
            page = (
                client.table("articles")
                .select("id, title, summary, full_text")
                .order("id", desc=True)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
        except Exception as e:
            logger.error(f"Article sayfası alınamadı (offset={offset}): {e}")
            raise

        if not page.data:
            break

        for a in page.data:
            if a["id"] not in embedded_set:
                unembedded.append(a)

        if len(page.data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    logger.info(f"{len(unembedded)} unembedded article(s) found")
    return unembedded


def embed_text(text: str, openai_client) -> list[float]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
                timeout=30
            )
            return response.data[0].embedding
        except RateLimitError:
            wait = 2 ** (attempt + 1)
            logger.warning(f"Embedding rate limit, retrying in {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
            last_error = "rate limit"
        except APITimeoutError:
            wait = 2 ** attempt
            logger.warning(f"Embedding timeout, retrying in {wait}s (attempt {attempt + 1})")
            time.sleep(wait)
            last_error = "timeout"
        except APIError as e:
            logger.error(f"OpenAI API hatası (embedding): {e}")
            raise
    raise RuntimeError(f"Embedding başarısız ({last_error}), {len(text)} karakterlik metin embed edilemedi.")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    try:
        encoder = tiktoken.get_encoding("cl100k_base")
        tokens = encoder.encode(text)
    except Exception as e:
        logger.warning(f"tiktoken hatası, boşluk bazlı bölmeye düşülüyor: {e}")
        words = text.split()
        chunks = []
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunks.append(" ".join(words[start:end]))
            start += chunk_size - overlap
        return chunks if chunks else [text]

    if len(tokens) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk_tokens = tokens[start:end]
        chunk_text = encoder.decode(chunk_tokens)
        chunks.append(chunk_text)
        start += chunk_size - overlap

    return chunks


def run_embedding():
    from openai import OpenAI

    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.error(f"Supabase bağlantı hatası: {e}")
        return 0

    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=30)
    except Exception as e:
        logger.error(f"OpenAI client oluşturulamadı: {e}")
        return 0

    try:
        articles = get_unembedded_articles(supabase)
    except Exception as e:
        logger.error(f"Makaleler alınamadı: {e}")
        return 0

    if not articles:
        logger.info("No articles to embed.")
        return 0

    total_chunks = 0
    inserted_chunks = []

    for article in articles:
        text_parts = []
        if article.get("title"):
            text_parts.append(article["title"])
        if article.get("summary"):
            text_parts.append(article["summary"])
        if article.get("full_text"):
            text_parts.append(article["full_text"])

        combined = " | ".join(text_parts)
        if not combined.strip():
            logger.warning(f"Skipping article {article['id']}: no text content")
            continue

        try:
            chunks = chunk_text(combined)
        except Exception as e:
            logger.error(f"Article {article['id']} chunk hatası: {e}, atlanıyor.")
            continue

        logger.info(f"Article {article['id']}: {len(chunks)} chunk(s)")

        for i, chunk in enumerate(chunks):
            try:
                vector = embed_text(chunk, openai_client)
            except Exception as e:
                logger.error(f"Article {article['id']} chunk {i} embedding hatası: {e}, atlanıyor.")
                continue

            inserted_chunks.append({
                "article_id": article["id"],
                "embedding": vector,
                "chunk_text": chunk,
                "chunk_index": i,
            })
            total_chunks += 1

            if len(inserted_chunks) >= BATCH_SIZE:
                try:
                    supabase.table("article_embeddings").insert(inserted_chunks).execute()
                    logger.info(f"Batch insert: {len(inserted_chunks)} chunk yazıldı.")
                    inserted_chunks = []
                except Exception as e:
                    logger.error(f"Batch insert hatası: {e}")

    if inserted_chunks:
        try:
            supabase.table("article_embeddings").insert(inserted_chunks).execute()
            logger.info(f"Final batch: {len(inserted_chunks)} chunk yazıldı.")
        except Exception as e:
            logger.error(f"Final batch insert hatası: {e}")

    logger.info(f"Done. {total_chunks} embedding(s) written.")
    return total_chunks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_embedding()
