import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client

from pipeline.rag.chunker import ChunkerFactory

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
JINA_API_KEY = os.getenv("JINA_API_KEY")

CHUNK_STRATEGY = "token"
PARENT_SIZE = 800
CHILD_SIZE = 256
CHILD_OVERLAP = 50
PAGE_SIZE = 1000
BATCH_EMBED = 64
BATCH_INSERT = 50
EMBED_DIM = 1024
EMBED_MODEL_NAME = "jina-embeddings-v3"
EMBED_MODEL_VERSION = "jina-v3-token"
EMBED_COLUMN = "embedding"
MIN_TEXT_LEN = 300


class Embedder(ABC):
    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class JinaEmbedder(Embedder):
    def __init__(self, model_name: str = EMBED_MODEL_NAME, api_key: Optional[str] = None):
        self._model_name = model_name
        self._api_key = api_key or JINA_API_KEY
        self._client = None
        self._dimension = EMBED_DIM

    def _load(self):
        if self._client is not None:
            return
        if not self._api_key:
            raise RuntimeError("JINA_API_KEY tanimli degil (.env kontrol et)")
        try:
            from openai import OpenAI
            self._client = OpenAI(
                base_url="https://api.jina.ai/v1",
                api_key=self._api_key,
            )
            logger.info(f"Jina embedder hazir: {self._model_name} ({self._dimension}-dim)")
        except Exception as e:
            logger.error(f"Jina client acilamadi: {e}")
            raise

    def embed_batch(self, texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
        self._load()
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_EMBED):
            chunk = texts[i:i + BATCH_EMBED]
            try:
                resp = self._client.embeddings.create(
                    model=self._model_name,
                    input=chunk,
                    encoding_format="float",
                    dimensions=self._dimension,
                    extra_body={"task": task},
                )
                chunk_vecs = [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
                out.extend(chunk_vecs)
                logger.info(f"Jina embed batch {i}-{i+len(chunk)} ({len(chunk)} metin)")
            except Exception as e:
                logger.error(f"Jina embed hatasi (batch {i}): {e}")
                raise
        return out

    def embed(self, text: str, task: str = "retrieval.passage") -> list[float]:
        vecs = self.embed_batch([text], task=task)
        return vecs[0] if vecs else []

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name


class EmbedderFactory:
    _providers = {
        "jina": JinaEmbedder,
    }

    @classmethod
    def create(cls, provider: str = "jina", **kwargs) -> Embedder:
        provider = provider.lower()
        if provider not in cls._providers:
            logger.warning(f"Bilinmeyen provider '{provider}', jina kullaniliyor")
            provider = "jina"
        try:
            return cls._providers[provider](**kwargs)
        except Exception as e:
            logger.error(f"Embedder olusturulamadi ({provider}): {e}")
            raise


def get_embedder() -> Embedder:
    model_name = os.getenv("RAG_EMBED_MODEL", EMBED_MODEL_NAME)
    logger.info(f"Embedding model: {model_name}")
    return JinaEmbedder(model_name=model_name)


def get_unembedded_articles(client, only_today: bool = True) -> list:
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        import psycopg2
        import psycopg2.extras
        from dotenv import load_dotenv

        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL .env'de tanimli degil")

        conn = psycopg2.connect(dsn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if only_today:
            cur.execute("""
                SELECT id, title, summary, full_text, published_at
                FROM articles
                WHERE full_text IS NOT NULL
                  AND length(full_text) >= %s
                  AND published_at >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM article_embeddings ae
                      WHERE ae.article_id = articles.id
                        AND ae.model_version = %s
                  )
                ORDER BY id DESC
            """, (MIN_TEXT_LEN, today, EMBED_MODEL_VERSION))
        else:
            cur.execute("""
                SELECT id, title, summary, full_text, published_at
                FROM articles
                WHERE full_text IS NOT NULL
                  AND length(full_text) >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM article_embeddings ae
                      WHERE ae.article_id = articles.id
                        AND ae.model_version = %s
                  )
                ORDER BY id DESC
            """, (MIN_TEXT_LEN, EMBED_MODEL_VERSION))

        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Atilacak article'lar alinamadi: {e}")
        raise

    result = [dict(r) for r in rows]
    logger.info(f"{len(result)} islenmemis article (NOT EXISTS SQL)")
    return result


BOILERPLATE_PATTERNS = [
    r"haberin devamı için",
    r"haberin devamini okumak",
    r"yazının devamı",
    r"yazinin devami",
    r"daha fazla oku",
    r"için tıklayın",
    r"icin tiklayin",
    r"read more",
    r"click here",
    r"bültenimize abone ol",
    r"bultenimize abone ol",
    r"e-posta adresinizi",
    r"eposta adresinizi",
    r"gizlilik politikası",
    r"gizlilik politikasi",
    r"çerez politikası",
    r"cerez politikasi",
    r"kaynak gösterilmeden",
    r"kaynak gosterilmeden",
    r"alarak haberlerimizi",
    r"tercih edilen kaynak",
    r"haberlerimizi google",
]


def clean_text(text: str) -> str:
    import re
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def combine_article_text(article: dict) -> str:
    parts = []
    if article.get("title"):
        parts.append(article["title"])
    if article.get("full_text"):
        parts.append(clean_text(article["full_text"]))
    return " | ".join(parts)


def _build_rows_for_article(article: dict, chunker, embedder: Embedder) -> list[dict]:
    combined = combine_article_text(article)
    if not combined.strip():
        logger.warning(f"Article {article['id']}: metin yok, atlaniyor")
        return []

    try:
        chunk_pairs = chunker.split_with_parent(
            combined,
            parent_size=PARENT_SIZE,
            child_size=CHILD_SIZE,
            overlap=CHILD_OVERLAP,
        )
    except Exception as e:
        logger.error(f"Article {article['id']} chunk hatasi: {e}")
        return []

    if not chunk_pairs:
        chunk_pairs = [{"chunk_text": combined, "parent_text": combined}]

    child_texts = [p["chunk_text"] for p in chunk_pairs]
    parent_texts = [p["parent_text"] for p in chunk_pairs]

    try:
        vectors = embedder.embed_batch(child_texts, task="retrieval.passage")
    except Exception as e:
        logger.error(f"Article {article['id']} embed hatasi: {e}")
        return []

    if len(vectors) != len(chunk_pairs):
        logger.error(
            f"Article {article['id']}: vector sayisi ({len(vectors)}) != chunk sayisi ({len(chunk_pairs)})"
        )
        return []

    rows = []
    for i, (vec, child_text, parent_text) in enumerate(zip(vectors, child_texts, parent_texts)):
        rows.append({
            "article_id": article["id"],
            EMBED_COLUMN: vec,
            "chunk_text": child_text,
            "parent_text": parent_text,
            "chunk_index": i,
            "model_version": EMBED_MODEL_VERSION,
        })
    return rows


def _upsert_batch(client, rows: list[dict]) -> int:
    if not rows:
        return 0
    try:
        client.table("article_embeddings").upsert(
            rows,
            on_conflict="article_id,chunk_index,model_version",
        ).execute()
        logger.info(f"Upsert: {len(rows)} chunk yazildi.")
        return len(rows)
    except Exception as e:
        logger.error(f"Upsert hatasi: {e}")
        try:
            client.table("article_embeddings").insert(rows).execute()
            logger.info(f"Fallback insert: {len(rows)} chunk yazildi.")
            return len(rows)
        except Exception as e2:
            logger.error(f"Fallback insert de basarisiz: {e2}")
            return 0


def run_embedding(clean: bool = False, only_today: bool = True):
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.error(f"Supabase baglanti hatasi: {e}")
        return 0

    if clean:
        logger.info("Tum embedding'ler siliniyor...")
        try:
            supabase.table("article_embeddings").delete().neq("id", 0).execute()
            logger.info("Tum embedding'ler silindi.")
        except Exception as e:
            logger.error(f"Clean hatasi: {e}")
            return 0

    try:
        embedder = get_embedder()
    except Exception as e:
        logger.error(f"Embedder olusturulamadi: {e}")
        return 0

    try:
        chunker = ChunkerFactory.create(CHUNK_STRATEGY)
        logger.info(f"Chunk stratejisi: {CHUNK_STRATEGY}")
    except Exception as e:
        logger.error(f"Chunker olusturulamadi: {e}")
        return 0

    try:
        articles = get_unembedded_articles(supabase, only_today=only_today)
    except Exception as e:
        logger.error(f"Makaleler alinamadi: {e}")
        return 0

    if not articles:
        logger.info("Embed article yok.")
        return 0

    total_chunks = 0
    buffer: list[dict] = []

    for article in articles:
        rows = _build_rows_for_article(article, chunker, embedder)
        if not rows:
            continue
        logger.info(f"Article {article['id']}: {len(rows)} chunk embed edildi")
        buffer.extend(rows)
        total_chunks += len(rows)

        while len(buffer) >= BATCH_INSERT:
            written = _upsert_batch(supabase, buffer[:BATCH_INSERT])
            buffer = buffer[BATCH_INSERT:]
            if not written and buffer == []:
                break

    _upsert_batch(supabase, buffer)

    logger.info(f"Tamamlandi. {total_chunks} embedding yazildi.")
    return total_chunks


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="Tum embedding'leri sil, yeniden embed")
    parser.add_argument("--all", action="store_true", help="Tum gecmisi embed et (sadece bugun degil)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_embedding(clean=args.clean, only_today=not args.all)