-- ============================================================
-- Migration: BAAI/bge-m3 (1024-dim) -- Eski model 384-dim idi
-- 
-- Çalıştırma sırası:
--   1. Bu SQL'i Supabase SQL Editor'de çalıştır
--   2. pipeline'da: python -m pipeline.rag.embed --clean
--   3. API restart
-- ============================================================

-- 1. Eski indeksi düşür
DROP INDEX IF EXISTS idx_embeddings_vector_new;

-- 2. Kolon tipini 384 → 1024'e çek (pgVector otomatik cast yapar)
ALTER TABLE article_embeddings
  ALTER COLUMN embedding_new TYPE vector(1024);

-- 3. Yeni indeks (1024-dim için)
CREATE INDEX IF NOT EXISTS idx_embeddings_vector_new
  ON article_embeddings USING ivfflat (embedding_new vector_cosine_ops)
  WITH (lists = 100);

-- 4. search_articles RPC fonksiyonu zaten embedding_new kullanıyor, değişiklik gerekmez.
