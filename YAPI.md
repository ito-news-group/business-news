# Proje Süreci ve Dosya Yapısı

## Ekip

| Kişi | Alan |
|---|---|
| **İsmail** | Supabase (SQL), Playwright (scraping), FastAPI, Docker, Cron Job, GitHub |
| **Esad** | GPT-4o-mini entegrasyonu — sektör sınıflandırma + haber özeti + günlük sektör özeti |
| **Harun & Kaan** | RAG sistemi — embedding, vektör arama, chatbot endpoint |
| **Burcu** | BERT modeli — eğitim + servis + duygu skoru |
| **Tolunay** | React frontend, mail tasarımı |

---

## Pipeline Akışı (Her Sabah 06:30)

```
[Cron 06:30 — İsmail'in kurduğu Docker container]
        │
        ▼
1. scraper.py çalışır
   → istanbulticaretgazetesi.com/son-dakika açılır
   → scroll ederek tüm haberler yüklenir
   → her haberin detay sayfasına girilir
   → başlık, tam metin, resim URL, yazar, tarih çekilir
   → Supabase articles tablosuna yazılır
        │
        ▼
2. process.py çalışır  [ESAD]
   → articles tablosundan bugünün haberlerini alır
   → her haber için tek GPT-4o-mini çağrısında hem sektör hem 3 bullet point özet alınır
   → articles tablosu güncellenir: sector + summary kolonları
        │
        ▼
3. daily_sector_summary.py çalışır  [ESAD]
   → 2. adım bittikten sonra çalışır (sektör bilgisi hazır olmalı)
   → articles tablosundaki bugünün haberlerini sektöre göre gruplar
   → her sektör için GPT-4o-mini ile "bugün bu sektörde ne oldu" özeti üretir
   → daily_summaries tablosuna yazılır (sektör başına bir satır)
        │
        ▼
4. bert_client.py çalışır  [BURCU]
   → articles tablosundan bugünün haberlerini alır
   → her haber Hugging Face Spaces'teki BERT servisine gönderilir
   → duygu skoru alınır
   → articles tablosu güncellenir: sentiment_bert, sentiment_score_bert
        │
        ▼
5. embed.py çalışır  [HARUN & KAAN]
   → articles tablosundan embedding'i olmayan bugünün haberlerini alır
   → her haber OpenAI text-embedding-3-small ile embed edilir
   → article_embeddings tablosuna yazılır (pgVector formatında)
        │
        ▼
6. send.py çalışır  [TOLUNAY]
   → daily_summaries tablosundan bugünün özetlerini alır
   → Jinja2 HTML şablonu ile bülten oluşturulur
   → subscribers tablosundan aktif aboneler alınır
   → Resend API ile e-posta gönderilir
   → newsletters tablosuna kayıt yazılır
        │
        ▼
[07:00 — Abonelere e-posta teslim]
```

---

## Gün İçi — Kullanıcı Frontend'i Açar

```
Tolunay'ın React uygulaması (Vercel)
        │
        ├── GET /api/sectors          → sektör listesi
        ├── GET /api/articles         → haberler (başlık, özet, resim, tarih, sektör)
        ├── GET /api/summaries        → günlük sektör özetleri
        ├── GET /api/summaries/sentiment-trend → 30 günlük duygu trendi grafiği
        └── POST /api/rag/ask         → kullanıcı soru sorar, RAG cevap verir
```

---

## RAG Sistemi Nasıl Çalışır?

RAG'ın iki ayrı parçası var:

### Parça 1 — Embedding (pipeline, günde bir kere)
```
embed.py çalışır (sabah pipeline'ında)
   → articles tablosundan yeni haberleri alır
   → title + summary + full_text birleştirilir
   → OpenAI text-embedding-3-small API'ye gönderilir
   → 1536 boyutlu vektör döner
   → article_embeddings tablosuna yazılır
   (pgVector bu vektörü saklar, benzerlik araması için kullanır)
```

### Parça 2 — Soru-Cevap (anlık, kullanıcı soru sorduğunda)
```
Kullanıcı soruyu yazar (React UI)
        ↓
POST /api/rag/ask → FastAPI (İsmail'in kurduğu, Harun & Kaan dolduracak)
        ↓
Soru metni OpenAI ile embed edilir (vektöre çevrilir)
        ↓
pgVector'de cosine similarity araması yapılır
   → En alakalı 5 haber parçası bulunur
   → Sektör filtresi varsa ona göre daralır
        ↓
Bulunan haber metinleri + kullanıcı sorusu GPT-4o-mini'ye gönderilir
   Prompt: "Aşağıdaki haberlere göre soruyu 1-2 cümleyle cevapla: ..."
        ↓
Cevap + kullanılan article id'leri kullanıcıya döner
        ↓
React UI'da cevap + kaynak haberler gösterilir
```

**Önemli:** RAG sürekli arka planda çalışmaz. Embedding sabah bir kere yazılır, soru-cevap ise kullanıcı sorduğunda anlık tetiklenir.

---

## Supabase Python Client Nedir?

Supabase'in resmi Python kütüphanesi. PostgreSQL'e HTTP üzerinden bağlanır, sektör standardı bir araç.

```python
from supabase import create_client

client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Veri okuma
result = client.table("articles").select("*").eq("sector", "finans").execute()

# Veri yazma
client.table("articles").insert({...}).execute()

# Veri güncelleme
client.table("articles").update({"sector": "finans"}).eq("id", 1).execute()
```

### İki Farklı Key Var

| Key | Yetki | Nerede Kullanılır |
|---|---|---|
| `anon` key | Sınırlı, RLS kurallarına tabi | React frontend (Tolunay) |
| `service_role` key | Tam yetki, her şeyi okur/yazar | Python pipeline ve scraper (İsmail, Esad, Burcu, Harun & Kaan) |

`service_role` key `.env` dosyasında tutulur, GitHub'a gitmez. Her ekip üyesi kendi `.env`'ini `.env.example`'a bakarak doldurur.

---

## Dosya Yapısı

```
business-news/
│
├── .env                        ← Gerçek key'ler — GitHub'a gitmiyor
├── .env.example                ← Şablon — ekip buraya bakarak .env'ini doldurur
├── .gitignore
├── README.md
├── docker-compose.yml          ← İsmail — api + pipeline container'larını tanımlar
│
├── db/
│   └── schema.sql              ← İsmail — Supabase SQL Editor'a bir kere çalıştırılır
│                                 Tüm tablolar + pgVector + search_articles() fonksiyonu
│
├── docker/
│   ├── Dockerfile.api          ← İsmail — FastAPI Docker imajı
│   └── Dockerfile.pipeline     ← İsmail — Scraper + cron Docker imajı
│
├── scraper/                    ← İSMAİL
│   ├── scraper.py              ← Playwright scraper — siteyi çeker, articles'a yazar
│   └── requirements.txt
│
├── api/                        ← İSMAİL (iskelet), HARUN & KAAN (rag.py)
│   ├── main.py                 ← FastAPI başlangıç, CORS, router'lar
│   ├── db.py                   ← Supabase bağlantısı
│   ├── requirements.txt
│   └── routers/
│       ├── health.py           ← GET /health
│       ├── articles.py         ← GET /api/articles, /api/articles/{id}
│       ├── summaries.py        ← GET /api/summaries, /sentiment-trend
│       ├── sectors.py          ← GET /api/sectors
│       ├── rag.py              ← POST /api/rag/ask — HARUN & KAAN dolduracak
│       └── newsletter.py       ← POST /subscribe, DELETE /unsubscribe
│
└── pipeline/
    ├── run.py                  ← İsmail — orkestratör, adımları sırayla çağırır
    ├── gpt/                    ← ESAD
    │   ├── process.py          ← tek GPT çağrısında sektör + özet → articles günceller
    │   └── daily_sector_summary.py ← sektör bazlı günlük özet → daily_summaries'e yazar
    ├── rag/                    ← HARUN & KAAN
    │   └── embed.py            ← OpenAI embedding → article_embeddings'e yazar
    ├── bert/                   ← BURCU
    │   └── bert_client.py      ← HF Spaces BERT servisine istek → articles günceller
    └── newsletter/             ← TOLUNAY
        └── send.py             ← Jinja2 bülten + Resend API ile gönderim
```

---

## Veritabanı Tabloları

| Tablo | Kim yazar | Ne saklar |
|---|---|---|
| `articles` | İsmail (scraper) | url, title, full_text, image_url, author, published_at |
| `articles` | Esad (process.py) | sector + summary (tek adımda) |
| `articles` | Burcu (BERT) | sentiment_bert, sentiment_score_bert |
| `daily_summaries` | Esad (daily_sector_summary.py) | sektör bazlı günlük özet — her sektör için bir satır |
| `article_embeddings` | Harun & Kaan | pgVector embedding'ler |
| `subscribers` | İsmail (API) | email, name, sectors |
| `newsletters` | Tolunay | gönderilen bültenler |
| `pipeline_runs` | İsmail (run.py) | her adımın logu |
| `chat_sessions` | Harun & Kaan | soru-cevap geçmişi |

**Not:** `sentiment_gpt`, `sentiment_score_gpt` kolonları şemada var ama kullanılmıyor.
Burcu'nun BERT modeli hazır olana kadar geçici dolgu için bırakıldı, boş kalması sorun değil.

---

## Kişi Bazlı Özet

### İsmail
- `db/schema.sql` → Supabase'e çalıştır
- `scraper/scraper.py` → Playwright ile haberleri çek, articles'a yaz
- `api/` → FastAPI iskeletini kur, endpoint'leri yaz
- `pipeline/run.py` → tüm adımları sırayla çağıran orkestratör
- `docker/` + `docker-compose.yml` → container yapısı
- GitHub org + repo yönetimi, `.env` dağıtımı

### Esad
- `pipeline/gpt/process.py` → her haber için tek GPT-4o-mini çağrısında sektör + 3 bullet point özet al, articles tablosunu güncelle (sector, summary)
- `pipeline/gpt/daily_sector_summary.py` → process.py bittikten sonra çalışır, sektöre göre grupla, günlük sektör özeti üret, daily_summaries tablosuna yaz
- Supabase bağlantısı: doğrudan Python client, service_role key
- **Not:** `daily_summaries` tablosu her haberin özetini değil, sektör bazlı günlük tek özeti tutar. Her haberin özeti `articles.summary` kolonundadır.

### Harun & Kaan
- `pipeline/rag/embed.py` → yeni haberleri embed et, article_embeddings'e yaz
- `api/routers/rag.py` → POST /api/rag/ask endpoint'ini doldur
- Supabase'de `search_articles()` RPC fonksiyonunu test et
- Embedding: doğrudan Python client / Chatbot: FastAPI üzerinden api/db.py

### Burcu
- Colab Pro+'da Türkçe BERT fine-tune et (Kaggle Twitter/Trendyol datası)
- Modeli Hugging Face Hub'a yükle
- Hugging Face Spaces'te FastAPI servisi aç (POST /predict)
- `pipeline/bert/bert_client.py` → servise istek at, articles.sentiment_bert güncelle

### Tolunay
- Ayrı repo: `business-news-front`
- React ile frontend yaz, Vercel'e deploy et
- API endpoint'leri: /api/articles, /api/summaries, /api/sectors, /api/rag/ask
- `pipeline/newsletter/send.py` → Jinja2 HTML mail şablonu tasarla, Resend API ile gönderim yaz

---

## Servisler

| Servis | Platform | Ücret |
|---|---|---|
| React frontend | Vercel | Ücretsiz |
| FastAPI | Render.com | Ücretsiz |
| Pipeline cron | Render.com cron job | Ücretsiz |
| BERT servisi | Hugging Face Spaces | Ücretsiz |
| Veritabanı | Supabase | Ücretsiz |
| E-posta | Resend (3000/ay) | Ücretsiz |
| Model eğitimi | Colab Pro+ (bir kere) | Zaten var |
