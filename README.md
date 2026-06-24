# İTO News Automation

İstanbul Ticaret Gazetesi haberlerini otomatik çeken, sınıflandıran, özetleyen ve abonelere bülten gönderen sistem.

## Ekip Görev Dağılımı

| Kişi | Alan | Klasör |
|------|------|--------|
| İsmail | Scraper, DB, FastAPI, Docker | `scraper/`, `db/`, `api/`, `docker/` |
| 2. Kişi | LLM entegrasyonu (GPT-4o-mini) | `pipeline/classification/`, `pipeline/summarization/` |
| 3. Kişi | RAG sistemi | `pipeline/rag/` |
| 4. Kişi | BERT duygu modeli | `pipeline/bert/` |
| 5. Kişi | React frontend | ayrı repo: `business-news-front` |
| 6. Kişi | Loglama + destek | `logs/`, `pipeline/newsletter/` |

## Kurulum

```bash
cp .env.example .env
# .env dosyasını doldurun

docker-compose up --build
```

## Mimari

```
Cron 06:30 → Scraper → PostgreSQL/pgVector
                              ↓
                    GPT-4o-mini (sektör + duygu)
                    BERT servisi (duygu)
                              ↓
                    Agregasyon + Özet
                              ↓
                    FastAPI ← React Frontend
                         ↓
                    Resend (e-posta bülteni)
```

## Teknoloji

- **Backend:** Python, FastAPI
- **Scraper:** Playwright
- **DB:** Supabase PostgreSQL + pgVector
- **LLM:** GPT-4o-mini
- **ML:** BERT (Türkçe duygu analizi)
- **Mail:** Resend
- **Container:** Docker + Docker Compose
- **Frontend:** React (ayrı repo)
