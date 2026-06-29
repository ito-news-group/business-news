-- ============================================================
-- Migration: BAAI/bge-m3 -> Jina Embeddings v3 (1024-dim)
-- Çalıştırma sırası:
--   1. Bu SQL'i Supabase SQL Editor'de çalıştır (bir kere)
--   2. pipeline'da: python -m pipeline.rag.embed --clean --all
--      (tüm makaleleri sıfırdan Jina ile re-embed eder)
--   3. API restart
-- ============================================================

-- 1. Eski ivfflat indeksini düşür
DROP INDEX IF EXISTS idx_embeddings_vector;
DROP INDEX IF EXISTS idx_embeddings_vector_new;
DROP INDEX IF EXISTS idx_embeddings_article_id;

-- 2. Kolon tipini 1024'e çek (Jina Embeddings v3)
ALTER TABLE article_embeddings
  ALTER COLUMN embedding TYPE vector(1024);

-- 3. parent_text kolonu ekle (yoksa)
ALTER TABLE article_embeddings
  ADD COLUMN IF NOT EXISTS parent_text TEXT;

-- 4. model_version kolonu ekle (çoklu model desteği)
ALTER TABLE article_embeddings
  ADD COLUMN IF NOT EXISTS model_version TEXT NOT NULL DEFAULT 'jina-v3-v1';

-- 5. chunk_index NOT NULL + default
ALTER TABLE article_embeddings
  ALTER COLUMN chunk_index SET NOT NULL,
  ALTER COLUMN chunk_index SET DEFAULT 0;

-- 6. Unique constraint (idempotent upsert için)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'article_embeddings_article_id_chunk_index_model_v_key'
    ) THEN
        ALTER TABLE article_embeddings
          ADD CONSTRAINT article_embeddings_article_id_chunk_index_model_v_key
          UNIQUE (article_id, chunk_index, model_version);
    END IF;
END $$;

-- 7. Eski embedding_new kolonu varsa düşür (geçiş leftover)
ALTER TABLE article_embeddings
  DROP COLUMN IF EXISTS embedding_new;

-- 8. Yeni HNSW indeksi (Jina 1024-dim için — ivfflat yerine daha iyi recall)
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
  ON article_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_embeddings_article_id
  ON article_embeddings(article_id);

-- 9. articles tablosuna tsv kolonu + GIN (yoksa ekle)
ALTER TABLE articles
  ADD COLUMN IF NOT EXISTS tsv tsvector
  GENERATED ALWAYS AS (
    to_tsvector('turkish',
      coalesce(title, '') || ' ' ||
      coalesce(summary, '') || ' ' ||
      coalesce(full_text, '')
    )
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_articles_tsv
  ON articles USING gin(tsv);

-- 10. search_articles() RPC'sini güncelle (1024-dim + parent_text + model_version)
CREATE OR REPLACE FUNCTION search_articles(
    query_embedding vector(1024),
    sector_filter   text DEFAULT NULL,
    match_count     int  DEFAULT 5
)
RETURNS TABLE (
    article_id  int,
    chunk_text  text,
    parent_text text,
    chunk_index int,
    similarity  float
)
LANGUAGE sql AS $$
    SELECT
        ae.article_id,
        ae.chunk_text,
        ae.parent_text,
        ae.chunk_index,
        1 - (ae.embedding <=> query_embedding) AS similarity
    FROM article_embeddings ae
    JOIN articles a ON a.id = ae.article_id
    WHERE ae.model_version = 'jina-v3-v1'
      AND (sector_filter IS NULL OR a.sector = sector_filter)
    ORDER BY ae.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- 11. fulltext_search_articles() RPC (BM25-style hybrid search için)
CREATE OR REPLACE FUNCTION fulltext_search_articles(
    query_text  text,
    match_count int DEFAULT 5
)
RETURNS TABLE (
    id      int,
    title   text,
    url     text,
    rank    real
)
LANGUAGE sql AS $$
    SELECT
        a.id,
        a.title,
        a.url,
        ts_rank(a.tsv, plainto_tsquery('turkish', query_text)) AS rank
    FROM articles a
    WHERE a.tsv @@ plainto_tsquery('turkish', query_text)
    ORDER BY rank DESC
    LIMIT match_count;
$$;