import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    def __init__(self, model_name: str = "seroe/bge-reranker-v2-m3-turkish-triplet", top_k: int = 3):
        self.model_name = model_name
        self.top_k = top_k
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
            logger.info(f"Reranker model loaded: {self.model_name}")
        except Exception as e:
            logger.error(f"Reranker model yuklenemedi ({self.model_name}): {e}")
            self._model = None

    def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return chunks
        self._load_model()
        if self._model is None:
            logger.warning("Reranker kullanilamiyor, siralamayi oldugu gibi dondur")
            return chunks

        try:
            pairs = [(query, c["chunk_text"]) for c in chunks]
            scores = self._model.predict(pairs)
            scored = list(zip(chunks, scores))
            scored.sort(key=lambda x: x[1], reverse=True)
            result = []
            for chunk, score in scored[: self.top_k]:
                chunk["rerank_score"] = float(score)
                result.append(chunk)
            return result
        except Exception as e:
            logger.error(f"Reranking sirasinda hata: {e}")
            return chunks
