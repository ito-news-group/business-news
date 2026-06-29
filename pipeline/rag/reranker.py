import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class CohereReranker:
    def __init__(self, model: str = "rerank-v3.5", top_k: int = 3, api_key: Optional[str] = None):
        self.model = model
        self.top_k = top_k
        self._api_key = api_key or os.getenv("COHERE_API_KEY")
        self._client = None

    def _load(self):
        if self._client is not None:
            return
        if not self._api_key:
            logger.warning("COHERE_API_KEY yok, rerank atlanacak")
            return
        try:
            import cohere
            self._client = cohere.ClientV2(self._api_key)
            logger.info(f"Cohere reranker hazir: {self.model}")
        except Exception as e:
            logger.error(f"Cohere client acilamadi: {e}")
            self._client = None

    def rerank(self, query: str, chunks: list[dict], top_k: Optional[int] = None) -> list[dict]:
        if not chunks:
            return chunks
        self._load()
        if self._client is None:
            logger.info("Reranker yok, mevcut siralama donuluyor")
            return chunks[: (top_k or self.top_k)]

        k = top_k or self.top_k
        documents = [c.get("chunk_text") or c.get("title") or "" for c in chunks]
        try:
            resp = self._client.rerank(
                model=self.model,
                query=query,
                documents=documents,
                top_n=k,
            )
            results = resp.results
            reranked = []
            for r in results:
                idx = r.index
                chunk = dict(chunks[idx])
                chunk["rerank_score"] = float(r.relevance_score) if r.relevance_score is not None else 0.0
                reranked.append(chunk)
            logger.info(f"Cohere rerank: {len(reranked)} sonuc")
            return reranked
        except Exception as e:
            logger.error(f"Cohere rerank hatasi: {e}")
            return chunks[:k]


def get_reranker(top_k: int = 3) -> Optional[CohereReranker]:
    if not os.getenv("COHERE_API_KEY"):
        return None
    return CohereReranker(top_k=top_k)