"""
pipeline/gpt/daily_sector_summary.py
Sorumlu: Esad

Görev:
  process.py bittikten sonra çalışır.
  Bugünün haberlerini sektöre göre gruplar.
  Her sektör için GPT-4o-mini ile "bugün bu sektörde ne oldu" özeti üretir.
  daily_summaries tablosuna yazar.

Çalışma sırası:
  pipeline/run.py tarafından process.py'dan SONRA çağrılır.
  (Sektör bilgisi hazır olmadan çalışamaz)

Girdi:
  Supabase articles tablosu — bugünün sector dolu kayıtları

Çıktı:
  daily_summaries tablosuna INSERT:
    - sector        : str
    - summary_date  : date
    - bullet_points : list[str]   ['• Madde 1', '• Madde 2', '• Madde 3']
    - headline      : str         en önemli gelişme tek cümle
    - article_count : int
    - avg_sentiment : float       (BERT skorlarının ortalaması, sonradan doldurulabilir)
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# TODO (Esad): Bu prompt'u geliştir
SECTOR_SUMMARY_PROMPT = """
Aşağıdaki {sector} sektörüne ait bugünkü haberleri analiz et:

1. En önemli 3 gelişmeyi bullet point olarak yaz (her biri "• " ile başlasın)
2. Günün en kritik gelişmesini tek cümleyle özetle (headline)

Haberler:
{articles_text}

Sadece JSON döndür:
{{"bullet_points": ["• ...", "• ...", "• ..."], "headline": "..."}}
"""


def get_todays_articles_by_sector(client) -> dict:
    """
    Bugünün haberlerini sektöre göre grupla.
    Dönüş: {"finans": [...], "insaat": [...], ...}
    """
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        client.table("articles")
        .select("id, title, summary, sector, sentiment_score_bert")
        .not_.is_("sector", "null")
        .gte("scraped_at", today)
        .execute()
    )

    grouped = {}
    for article in result.data:
        sector = article["sector"]
        if sector not in grouped:
            grouped[sector] = []
        grouped[sector].append(article)

    return grouped


def summarize_sector(sector: str, articles: list, openai_client) -> dict:
    """
    TODO (Esad): Bir sektörün haberlerini özetle.

    Dönüş:
    {
        "bullet_points": ["• ...", "• ...", "• ..."],
        "headline": "...",
        "article_count": 5,
        "avg_sentiment": 0.2
    }
    """
    # TODO: Haber başlıklarını + özetlerini birleştir
    # TODO: GPT-4o-mini'ye gönder
    # TODO: JSON parse et
    # TODO: avg_sentiment = sentiment_score_bert ortalaması (None olanları atla)
    raise NotImplementedError("Esad implement edecek")


def run_daily_sector_summary():
    """
    Ana fonksiyon — pipeline/run.py bu fonksiyonu çağırır.
    TODO (Esad): Her sektör için summarize_sector çağır,
    sonuçları daily_summaries tablosuna yaz.
    """
    # TODO: Supabase + OpenAI client oluştur
    # TODO: get_todays_articles_by_sector ile gruplu haberleri al
    # TODO: Her sektör için summarize_sector çağır
    # Örnek INSERT:
    # client.table("daily_summaries").upsert({
    #     "sector": sector,
    #     "summary_date": today,
    #     "bullet_points": result["bullet_points"],
    #     "headline": result["headline"],
    #     "article_count": result["article_count"],
    #     "avg_sentiment": result["avg_sentiment"],
    # }, on_conflict="sector,summary_date").execute()
    raise NotImplementedError("Esad implement edecek")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daily_sector_summary()
