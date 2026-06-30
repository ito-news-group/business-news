import logging
import tiktoken
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class Chunker(ABC):
    @abstractmethod
    def split(self, text: str) -> list[str]:
        ...

    @abstractmethod
    def split_with_parent(
        self, text: str, parent_size: int, child_size: int, overlap: int
    ) -> list[dict]:
        ...


class RecursiveChunker(Chunker):
    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 30):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _recursive_split(self, text: str, size: int, overlap: int) -> list[str]:
        separators = ["\n\n", "\n", ".", " ", ""]
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=size,
                chunk_overlap=overlap,
                separators=separators,
            )
            return splitter.split_text(text)
        except ImportError:
            logger.warning("langchain not available, falling back to character split")
            return self._fallback_split(text, size, overlap)

    def _fallback_split(self, text: str, size: int, overlap: int) -> list[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + size
            chunks.append(text[start:end])
            start += size - overlap
        return chunks if chunks else [text]

    def split(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        try:
            return self._recursive_split(text, self.chunk_size, self.chunk_overlap)
        except Exception as e:
            logger.error(f"Recursive chunk hatasi: {e}")
            return [text]

    def split_with_parent(
        self, text: str, parent_size: int = 400, child_size: int = 120, overlap: int = 30
    ) -> list[dict]:
        if not text or not text.strip():
            return []
        try:
            parents = self._recursive_split(text, parent_size, 0)
            result = []
            for parent in parents:
                children = self._recursive_split(parent, child_size, overlap)
                for child in children:
                    result.append({
                        "chunk_text": child,
                        "parent_text": parent,
                    })
            return result
        except Exception as e:
            logger.error(f"Parent-child chunk hatasi: {e}")
            return [{"chunk_text": text, "parent_text": text}]


class TokenChunker(Chunker):
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, encoding: str = "cl100k_base"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding = encoding

    def _token_split(self, text: str, size: int, overlap: int) -> list[str]:
        try:
            encoder = tiktoken.get_encoding(self.encoding)
            tokens = encoder.encode(text)
        except Exception:
            logger.warning("tiktoken hatasi, kelime bazli bolmeye dusuluyor")
            words = text.split()
            chunks = []
            start = 0
            while start < len(words):
                end = start + size
                chunks.append(" ".join(words[start:end]))
                start += size - overlap
            return chunks if chunks else [text]

        if len(tokens) <= size:
            return [text]

        chunks = []
        start = 0
        while start < len(tokens):
            end = start + size
            chunk_tokens = tokens[start:end]
            chunks.append(encoder.decode(chunk_tokens))
            start += size - overlap
        return chunks

    def split(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        try:
            return self._token_split(text, self.chunk_size, self.chunk_overlap)
        except Exception as e:
            logger.error(f"Token chunk hatasi: {e}")
            return [text]

    def split_with_parent(
        self, text: str, parent_size: int = 500, child_size: int = 150, overlap: int = 30
    ) -> list[dict]:
        if not text or not text.strip():
            return []
        try:
            parents = self._token_split(text, parent_size, 0)
            result = []
            for parent in parents:
                children = self._token_split(parent, child_size, overlap)
                for child in children:
                    result.append({
                        "chunk_text": child,
                        "parent_text": parent,
                    })
            return result
        except Exception as e:
            logger.error(f"Parent-child token chunk hatasi: {e}")
            return [{"chunk_text": text, "parent_text": text}]


class CharacterChunker(Chunker):
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _character_split(self, text: str, size: int, overlap: int) -> list[str]:
        try:
            from langchain_text_splitters import CharacterTextSplitter

            splitter = CharacterTextSplitter(
                chunk_size=size,
                chunk_overlap=overlap,
                separator="\n\n",
            )
            return splitter.split_text(text)
        except ImportError:
            logger.warning("langchain not available, falling back to raw split")
            chunks = []
            start = 0
            while start < len(text):
                end = start + size
                chunks.append(text[start:end])
                start += size - overlap
            return chunks if chunks else [text]

    def split(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        try:
            return self._character_split(text, self.chunk_size, self.chunk_overlap)
        except Exception as e:
            logger.error(f"Character chunk hatasi: {e}")
            return [text]

    def split_with_parent(
        self, text: str, parent_size: int = 1000, child_size: int = 300, overlap: int = 50
    ) -> list[dict]:
        if not text or not text.strip():
            return []
        try:
            parents = self._character_split(text, parent_size, 0)
            result = []
            for parent in parents:
                children = self._character_split(parent, child_size, overlap)
                for child in children:
                    result.append({
                        "chunk_text": child,
                        "parent_text": parent,
                    })
            return result
        except Exception as e:
            logger.error(f"Parent-child character chunk hatasi: {e}")
            return [{"chunk_text": text, "parent_text": text}]


class ChunkerFactory:
    _strategies = {
        "recursive": RecursiveChunker,
        "token": TokenChunker,
        "character": CharacterChunker,
    }

    @classmethod
    def create(cls, strategy: str = "recursive", **kwargs) -> Chunker:
        strategy = strategy.lower()
        if strategy not in cls._strategies:
            logger.warning(f"Bilinmeyen chunk stratejisi '{strategy}', recursive kullaniliyor")
            strategy = "recursive"
        try:
            return cls._strategies[strategy](**kwargs)
        except Exception as e:
            logger.error(f"Chunker olusturulamadi ({strategy}): {e}, recursive kullaniliyor")
            return RecursiveChunker(**kwargs)
