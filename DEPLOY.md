# ITO News — Deployment Rehberi

## Servisler

| Servis | Platform | URL | Kaynak |
|---|---|---|---|
| Backend API | **Render.com** | `https://ito-news-api.onrender.com` | Free 512MB |
| Pipeline Cron | Render.com (cron job) | ayni proje | Free |
| Frontend | **Vercel** | `https://ito-news.vercel.app` | Free |
| Veritabani | **Supabase** | `https://rddnhkxcopwstpflzplj.supabase.co` | Free |
| E-posta | **Resend** | API | 3000/ay free |

---

## 1. Supabase — Migration (Ismail, bir kerelik)

Supabase Dashboard > SQL Editor'da sunlari sirasiyla calistir:

1. `db/schema.sql` — tablolari ve RPC'leri olusturur
2. `db/migration-jina-v1.sql` — eski embedding'leri Jina v3 1024-dim'e gunceller

Alternatif: sifirdan kurulum icin sadece `db/schema.sql`.

---

## 2. Backend Deploy — Render (Ismail)

### Web Service

Render Dashboard > New > Web Service:

| Ayar | Deger |
|---|---|
| Repository | `github.com/ito-news-group/business-news` |
| Branch | `harun-rag` (sonra `main`) |
| Root Directory | _(bos)_ |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` |
| Plan | **Free** (512MB RAM, yeterli) |
| Health Check | `GET /health` |

### Environment Variables

Render Dashboard > Environment kismina ekle:

```
SUPABASE_URL=https://rddnhkxcopwstpflzplj.supabase.co
SUPABASE_KEY=eyJhbGci... (service_role key, .env'den al)
DATABASE_URL=postgresql://postgres:ItoProjesi2026!@db.rddnhkxcopwstpflzplj.supabase.co:5432/postgres
JINA_API_KEY=jina_... (Harun'dan al)
COHERE_API_KEY=yQao... (Harun'dan al)
OPENROUTER_API_KEY=sk-or-... (Harun'dan al)
OPENAI_API_KEY=sk-proj-... (Esad'in key'i)
API_KEY= (bos birak = dev mod, auth kapali)
```

**Onemli:** `DATABASE_URL` olmazsa arama calismaz (psycopg2 dogrudan PG baglanir).

### Pipeline Cron (istege bagli)

Ayni Render projesinde Cron Job olustur:

| Ayar | Deger |
|---|---|
| Command | `python -m pipeline.rag.embed` |
| Schedule | `30 6 * * *` (her sabah 06:30) |
| Timeout | 600s |

Pipeline her gun yeni haberleri Jina ile embed eder. Eski embed'ler korunur (idempotent).

---

## 3. Frontend Deploy — Vercel (Tolunay)

### Repository

`github.com/ito-news-group/business-news-front`

### Environment Variables (Vercel Dashboard)

```
VITE_API_URL=https://ito-news-api.onrender.com
```

### CORS

Backend `allow_origins=["*"]` — tum kaynaklara acik. Production'da Vercel URL'i ile daraltilabilir.

### Test

`demo.html`'i tarayicida ac, API URL olarak Render URL'ini yaz.

---

## 4. API Endpoint'leri (Tolunay)

### Haberler

| Method | Endpoint | Donus |
|---|---|---|
| `GET` | `/api/articles` | Tum haberler |
| `GET` | `/api/articles/{id}` | Tek haber |
| `GET` | `/api/sectors` | Sektor listesi |
| `GET` | `/api/summaries` | Gunluk sektor ozetleri |
| `GET` | `/api/summaries/sentiment-trend` | 30 gunluk duygu trendi |

### RAG Chatbot — POST /api/rag/ask

```json
// Request
{
  "question": "Finans sektorunde bu hafta neler oldu?",
  "sector": "finans"          // opsiyonel
}

// Response
{
  "query": "Finans sektorunde bu hafta neler oldu?",
  "answer": "Borsa ve altin deger kaybederken dolar yukseldi...",
  "total": 3,
  "results": [
    {
      "article_id": 67,
      "chunk_text": "...",
      "parent_text": "...detayli paragraf...",
      "similarity": 0.5588,
      "rerank_score": 0.5869,
      "title": "Borsa gunu yukselisle acti",
      "url": "https://istanbulticaretgazetesi.com/..."
    }
  ]
}
```

### Newsletter

| Method | Endpoint | Body |
|---|---|---|
| `POST` | `/api/newsletter/subscribe` | `{"email": "...", "name?": "..."}` |
| `DELETE` | `/api/newsletter/unsubscribe` | `{"email": "..."}` |

### Monitoring

| Method | Endpoint | Donus |
|---|---|---|
| `GET` | `/api/rag/metrics` | Son 60sn: istek sayisi, gecikme, stage kirlimlari |
| `GET` | `/api/rag/metrics/db` | DB: chunk sayisi, kapsama %'si |
| `GET` | `/health` | `{"status": "ok"}` |

---

## 5. Supabase Tablolari (bilgi)

| Tablo | Kim Yazar | Icerik |
|---|---|---|
| `articles` | scraper + gpt/process | Haberler |
| `article_embeddings` | pipeline/rag/embed | pgVector (1024-dim Jina) |
| `daily_summaries` | gpt/daily_sector_summary | Gunluk sektor ozetleri |
| `sectors` | static | Sektor listesi |
| `subscribers` | API | E-posta aboneleri |
| `newsletters` | newsletter/send | Gonderilen bultenler |
| `pipeline_runs` | pipeline/run | Adim loglari |
| `chat_sessions` | rag/ask | Soru-cevap gecmisi |

---

## 6. Verify

```bash
# Backend calisiyor mu?
curl https://ito-news-api.onrender.com/health

# RAG cevap veriyor mu?
curl -X POST https://ito-news-api.onrender.com/api/rag/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "finans sektoru"}'

# Monitoring
curl https://ito-news-api.onrender.com/api/rag/metrics
```

---

## 7. LLM Modeli Degistirme

Su an `pipeline/rag/llm_providers.py:34` satirinda model tanimli:

```python
self.model = "openai/gpt-4o-mini"
```

Alternatifler (hepsi OpenRouter uzerinden, ayni API key):

| Model | Hiz | Maliyet | Turkce |
|---|---|---|---|
| `openai/gpt-4o-mini` (su anki) | Orta | $0.15/1M | Iyi |
| `google/gemini-2.0-flash-001` | Hizli | $0.10/1M | Cok iyi |
| `anthropic/claude-3-haiku` | Hizli | $0.25/1M | Orta |
| `meta-llama/llama-3.3-70b-instruct` | Yavas | $0.20/1M | Iyi |
| `deepseek/deepseek-chat` | Orta | $0.14/1M | Iyi |

Degistirmek icin tek satir yeterli. `.env`'e `LLM_MODEL=google/gemini-2.0-flash-001` ekleyip kodu env'den okuyacak sekilde guncelle.
