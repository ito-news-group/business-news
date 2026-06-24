-- ============================================================
-- İTO News Automation - Veritabanı Şeması
-- Supabase SQL Editor'da çalıştırın
-- ============================================================

-- pgVector eklentisini aktif et (RAG için şart)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- KAYNAKLAR TABLOSU
-- Her haber kaynağı (ticaret odası sitesi) buraya eklenir.
-- Şu an sadece İTO var, ileride diğer iller eklenebilir.
-- ============================================================
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,          -- 'İstanbul Ticaret Gazetesi'
    city        TEXT NOT NULL,          -- 'istanbul'
    url         TEXT NOT NULL,          -- 'https://istanbulticaretgazetesi.com/son-dakika'
    config      JSONB,                  -- selector'lar ve scraper ayarları
                                        -- {"type": "scroll", "article_links": "h2 a", ...}
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Başlangıç verisi: İTO
INSERT INTO sources (name, city, url, config) VALUES (
    'İstanbul Ticaret Gazetesi',
    'istanbul',
    'https://istanbulticaretgazetesi.com/son-dakika',
    '{"type": "scroll", "article_links": "h2 a, h3 a", "title": "h1", "body": ".entry-content", "date": "time[datetime]", "image": "img.wp-post-image"}'
) ON CONFLICT DO NOTHING;

-- ============================================================
-- HABERLER TABLOSU
-- Scraper'ın yazdığı ham haber verileri
-- ============================================================
CREATE TABLE IF NOT EXISTS articles (
    id              SERIAL PRIMARY KEY,
    source_id       INTEGER REFERENCES sources(id) DEFAULT 1,  -- hangi siteden geldi
    url             TEXT NOT NULL UNIQUE,          -- duplicate detection için
    url_hash        VARCHAR(64) NOT NULL UNIQUE,   -- MD5 hash, hızlı lookup
    title           TEXT NOT NULL,
    summary         TEXT,                          -- GPT özeti (3 bullet point)
    full_text       TEXT,
    image_url       TEXT,                          -- haber görseli
    author          TEXT,
    published_at    TIMESTAMPTZ,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),

    -- GPT-4o-mini tarafından doldurulacak (pipeline/gpt/process.py)
    sector          TEXT,                          -- 'inşaat', 'finans', 'tekstil' ...
    sentiment_gpt   TEXT,                          -- şimdilik boş, BERT yeterli
    sentiment_score_gpt FLOAT,                     -- şimdilik boş, BERT yeterli

    -- BERT tarafından doldurulacak (pipeline/bert)
    sentiment_bert  TEXT,
    sentiment_score_bert FLOAT
);

-- İndeksler
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_sector ON articles(sector);
CREATE INDEX IF NOT EXISTS idx_articles_scraped_at ON articles(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash);
CREATE INDEX IF NOT EXISTS idx_articles_source_id ON articles(source_id);

-- ============================================================
-- SEKTÖRLER TABLOSU
-- Sabit liste - uygulama başlangıcında seed edilir
-- ============================================================
CREATE TABLE IF NOT EXISTS sectors (
    id      SERIAL PRIMARY KEY,
    slug    VARCHAR(50) UNIQUE NOT NULL,   -- 'insaat', 'finans'
    name    VARCHAR(100) NOT NULL          -- 'İnşaat', 'Finans'
);

INSERT INTO sectors (slug, name) VALUES
    ('insaat', 'İnşaat'),
    ('finans', 'Finans'),
    ('tekstil', 'Tekstil'),
    ('teknoloji', 'Teknoloji'),
    ('enerji', 'Enerji'),
    ('tarim', 'Tarım'),
    ('ihracat', 'İhracat & Dış Ticaret'),
    ('lojistik', 'Lojistik & Ulaşım'),
    ('turizm', 'Turizm'),
    ('saglik', 'Sağlık'),
    ('egitim', 'Eğitim'),
    ('perakende', 'Perakende'),
    ('otomotiv', 'Otomotiv'),
    ('gayrimenkul', 'Gayrimenkul'),
    ('diger', 'Diğer')
ON CONFLICT (slug) DO NOTHING;

-- ============================================================
-- GÜNLÜK ÖZETLER TABLOSU
-- GPT-4o-mini'nin ürettiği sektör bazlı günlük özetler
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_summaries (
    id              SERIAL PRIMARY KEY,
    sector          TEXT NOT NULL,
    summary_date    DATE NOT NULL,
    bullet_points   TEXT[],                -- ['• Madde 1', '• Madde 2', '• Madde 3']
    headline        TEXT,                  -- En önemli gelişme
    article_count   INTEGER DEFAULT 0,
    avg_sentiment   FLOAT,                 -- O günün ortalama duygu skoru
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(sector, summary_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_summaries_date ON daily_summaries(summary_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_summaries_sector ON daily_summaries(sector);

-- ============================================================
-- BÜLTENLER TABLOSU
-- Gönderilen her bülteni kayıt altına alır
-- ============================================================
CREATE TABLE IF NOT EXISTS newsletters (
    id              SERIAL PRIMARY KEY,
    send_date       DATE NOT NULL UNIQUE,
    subject         TEXT,
    html_content    TEXT,
    recipient_count INTEGER DEFAULT 0,
    sent_at         TIMESTAMPTZ,
    status          TEXT DEFAULT 'pending'  -- 'pending', 'sent', 'failed'
);

-- ============================================================
-- ABONE TABLOSU
-- ============================================================
CREATE TABLE IF NOT EXISTS subscribers (
    id              SERIAL PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    name            TEXT,
    sectors         TEXT[],                -- İlgilendiği sektörler, boşsa hepsi
    is_active       BOOLEAN DEFAULT TRUE,
    subscribed_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RAG - EMBEDDINGS TABLOSU
-- pgVector — haber metinlerinin vektör temsilleri
-- RAG arkadaşı bu tabloyu dolduracak
-- ============================================================
CREATE TABLE IF NOT EXISTS article_embeddings (
    id              SERIAL PRIMARY KEY,
    article_id      INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    embedding       vector(1536),          -- OpenAI text-embedding-3-small boyutu
    chunk_text      TEXT,                  -- Embed edilen metin parçası
    chunk_index     INTEGER DEFAULT 0,     -- Uzun metinler bölünürse sıra numarası
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- pgVector için cosine similarity indeksi (RAG aramaları için kritik)
CREATE INDEX IF NOT EXISTS idx_embeddings_vector 
    ON article_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_embeddings_article_id 
    ON article_embeddings(article_id);

-- ============================================================
-- RAG - SOHBET GEÇMİŞİ (opsiyonel, chatbot için)
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      UUID DEFAULT gen_random_uuid(),
    question        TEXT NOT NULL,
    answer          TEXT,
    sources         INTEGER[],             -- Kullanılan article id'leri
    sector_filter   TEXT,                  -- Hangi sektörde soruldu
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PIPELINE LOG TABLOSU
-- 6. kişinin (log arkadaşının) kullanacağı tablo
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              SERIAL PRIMARY KEY,
    run_date        DATE NOT NULL,
    stage           TEXT NOT NULL,   -- 'scraper', 'classification', 'summary', 'newsletter'
    status          TEXT NOT NULL,   -- 'success', 'failed', 'partial'
    articles_processed INTEGER DEFAULT 0,
    error_message   TEXT,
    duration_seconds FLOAT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

-- ============================================================
-- RAG - VEKTÖR ARAMA FONKSİYONU
-- Harun & Kaan'ın kullanacağı pgVector similarity search
-- Bu fonksiyon Supabase'de bir kere çalıştırılır.
-- ============================================================
CREATE OR REPLACE FUNCTION search_articles(
    query_embedding vector(1536),
    sector_filter   text DEFAULT NULL,
    match_count     int  DEFAULT 5
)
RETURNS TABLE (
    article_id  int,
    chunk_text  text,
    similarity  float
)
LANGUAGE sql AS $$
    SELECT
        ae.article_id,
        ae.chunk_text,
        1 - (ae.embedding <=> query_embedding) AS similarity
    FROM article_embeddings ae
    JOIN articles a ON a.id = ae.article_id
    WHERE (sector_filter IS NULL OR a.sector = sector_filter)
    ORDER BY ae.embedding <=> query_embedding
    LIMIT match_count;
$$;
