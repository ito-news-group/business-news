-- ============================================================
-- Migration: BAAI/bge-m3 -> Jina Embeddings v3 (1024-dim)
-- Calistirma sirasi:
--   1. Bu SQL'i Supabase SQL Editor'de calistir (bir kere)
--   2. pipeline'da: python -m pipeline.rag.embed --clean --all
--      (tum makaleleri sifirdan Jina ile re-embed eder)
--   3. API restart
-- ============================================================

BEGIN;

-- 1. Eski ivfflat indeksini dusur
DROP INDEX IF EXISTS idx_embeddings_vector;
DROP INDEX IF EXISTS idx_embeddings_vector_new;
DROP INDEX IF EXISTS idx_embeddings_article_id;

-- 2. Kolon tipini 1024'e cek (Jina Embeddings v3)
ALTER TABLE article_embeddings
  ALTER COLUMN embedding TYPE vector(1024);

-- 3. parent_text kolonu ekle (yoksa)
ALTER TABLE article_embeddings
  ADD COLUMN IF NOT EXISTS parent_text TEXT;

-- 4. model_version kolonu ekle (coklu model destegi)
ALTER TABLE article_embeddings
  ADD COLUMN IF NOT EXISTS model_version TEXT NOT NULL DEFAULT 'jina-v3-v1';

-- 5. chunk_index NOT NULL + default
ALTER TABLE article_embeddings
  ALTER COLUMN chunk_index SET NOT NULL,
  ALTER COLUMN chunk_index SET DEFAULT 0;

-- 6. Unique constraint (idempotent upsert icin)
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

-- 7. Eski embedding_new kolonu varsa dusur (gecis leftover)
ALTER TABLE article_embeddings
  DROP COLUMN IF EXISTS embedding_new;

-- 8. Yeni HNSW indeksi (Jina 1024-dim icin)
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

-- 10. chat_sessions tablosu (yoksa ekle)
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      UUID DEFAULT gen_random_uuid(),
    question        TEXT NOT NULL,
    answer          TEXT,
    sources         INTEGER[],
    sector_filter   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;
