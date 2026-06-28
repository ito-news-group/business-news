import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

from pipeline.rag.chunker import ChunkerFactory

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")

CHUNK_STRATEGY = "recursive"
PARENT_SIZE = 400
CHILD_SIZE = 120
CHILD_OVERLAP = 30
PAGE_SIZE = 1000
BATCH_SIZE = 20
EMBED_DIM = 1024
EMBED_MODEL_NAME = "BAAI/bge-m3"
EMBED_COLUMN = "embedding_new"
USE_RERANKER = True


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class HuggingFaceEmbedder(Embedder):
    def __init__(self, model_name: str = EMBED_MODEL_NAME):
        self._model_name = model_name
        self._model = None
        self._dimension = 0

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self._model_name,
                token=HF_TOKEN if HF_TOKEN else None,
            )
            self._dimension = self._model.get_embedding_dimension()
            logger.info(f"Embedding model loaded: {self._model_name} ({self._dimension}-dim)")
        except Exception as e:
            logger.error(f"Model yuklenemedi ({self._model_name}): {e}")
            raise

    def embed(self, text: str) -> list[float]:
        self._load()
        try:
            return self._model.encode(text).tolist()
        except Exception as e:
            logger.error(f"Embedding sirasinda hata: {e}")
            raise

    @property
    def dimension(self) -> int:
        self._load()
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name


class EmbedderFactory:
    _providers = {
        "huggingface": HuggingFaceEmbedder,
    }

    @classmethod
    def create(cls, provider: str = "huggingface", **kwargs) -> Embedder:
        provider = provider.lower()
        if provider not in cls._providers:
            logger.warning(f"Bilinmeyen provider '{provider}', huggingface kullaniliyor")
            provider = "huggingface"
        try:
            return cls._providers[provider](**kwargs)
        except Exception as e:
            logger.error(f"Embedder olusturulamadi ({provider}): {e}, huggingface'e dusuluyor")
            return HuggingFaceEmbedder(**kwargs)


def get_embedder() -> Embedder:
    model_name = os.getenv("RAG_EMBED_MODEL", EMBED_MODEL_NAME)
    logger.info(f"Embedding model: {model_name}")
    return HuggingFaceEmbedder(model_name=model_name)


def get_unembedded_articles(client, force: bool = False) -> list:
    try:
        rows = client.table("article_embeddings").select("article_id, embedding_new").execute()
        if force:
            embedded_set = {row["article_id"] for row in rows.data if row.get("embedding_new") is not None}
        else:
            embedded_set = {row["article_id"] for row in rows.data}
    except Exception as e:
        logger.error(f"Embedding ID'leri alinamadi: {e}")
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
            logger.error(f"Article sayfasi alinamadi (offset={offset}): {e}")
            raise

        if not page.data:
            break

        for a in page.data:
            text = a.get("full_text") or ""
            if a["id"] not in embedded_set and len(text) >= 300:
                unembedded.append(a)

        if len(page.data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    logger.info(f"{len(unembedded)} unembedded article(s) found")
    return unembedded


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
    if article.get("summary"):
        parts.append(clean_text(article["summary"]))
    if article.get("full_text"):
        parts.append(clean_text(article["full_text"]))
    return " | ".join(parts)


def run_embedding(clean: bool = False):
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.error(f"Supabase baglanti hatasi: {e}")
        return 0

    if clean:
        logger.info("Cleaning all existing embeddings...")
        try:
            supabase.table("article_embeddings").delete().neq("id", 0).execute()
            logger.info("All embeddings deleted.")
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
        articles = get_unembedded_articles(supabase, force=True)
    except Exception as e:
        logger.error(f"Makaleler alinamadi: {e}")
        return 0

    if not articles:
        logger.info("No articles to embed.")
        return 0

    total_chunks = 0
    inserted_chunks = []

    for article in articles:
        combined = combine_article_text(article)
        if not combined.strip():
            logger.warning(f"Skipping article {article['id']}: no text content")
            continue

        try:
            chunk_pairs = chunker.split_with_parent(
                combined,
                parent_size=PARENT_SIZE,
                child_size=CHILD_SIZE,
                overlap=CHILD_OVERLAP,
            )
        except Exception as e:
            logger.error(f"Article {article['id']} chunk hatasi: {e}, atlaniyor.")
            continue

        if not chunk_pairs:
            chunk_pairs = [{"chunk_text": combined, "parent_text": combined}]

        logger.info(f"Article {article['id']}: {len(chunk_pairs)} parent-child chunk(s)")

        for i, pair in enumerate(chunk_pairs):
            child_text = pair["chunk_text"]
            parent_text = pair["parent_text"]

            try:
                vector = embedder.embed(child_text)
            except Exception as e:
                logger.error(f"Article {article['id']} chunk {i} embedding hatasi: {e}, atlaniyor.")
                continue

            inserted_chunks.append({
                "article_id": article["id"],
                EMBED_COLUMN: vector,
                "chunk_text": child_text,
                "parent_text": parent_text,
                "chunk_index": i,
            })
            total_chunks += 1

            if len(inserted_chunks) >= BATCH_SIZE:
                try:
                    supabase.table("article_embeddings").insert(inserted_chunks).execute()
                    logger.info(f"Batch insert: {len(inserted_chunks)} chunk yazildi.")
                    inserted_chunks = []
                except Exception as e:
                    logger.error(f"Batch insert hatasi: {e}")

    if inserted_chunks:
        try:
            supabase.table("article_embeddings").insert(inserted_chunks).execute()
            logger.info(f"Final insert: {len(inserted_chunks)} chunk yazildi.")
        except Exception as e:
            logger.error(f"Final insert hatasi: {e}")

    logger.info(f"Done. {total_chunks} embedding(s) written.")
    return total_chunks


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="Delete all embeddings before re-embedding")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_embedding(clean=args.clean)
