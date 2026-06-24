"""
pipeline/bert/bert_client.py
Sorumlu: Burcu

Görev:
  Bugün scraper'ın çektiği haberleri Hugging Face Spaces'teki
  BERT servisine gönder, duygu skoru al, articles tablosunu güncelle.

Çalışma sırası:
  pipeline/run.py tarafından process.py'dan sonra çağrılır.

Girdi:
  Supabase articles tablosu — sentiment_bert IS NULL olan bugünün kayıtları

Çıktı:
  articles tablosu güncellenir:
    - sentiment_bert        : str    ('pozitif', 'negatif', 'nötr')
    - sentiment_score_bert  : float  (-1.0 ile 1.0 arası)

BERT Servisi:
  Burcu'nun Hugging Face Spaces'te açacağı FastAPI servisi.
  Endpoint: POST /predict
  Request:  {"text": "haber metni..."}
  Response: {"sentiment": "pozitif", "score": 0.87}

  Servis hazır olunca BERT_SERVICE_URL'i .env'e ekle.
"""

import os
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BERT_SERVICE_URL = os.getenv("BERT_SERVICE_URL")  # örn: https://burcu-bert.hf.space


def get_todays_unscored(client):
    """Bugün çekilmiş, henüz BERT skorlanmamış haberleri getir"""
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        client.table("articles")
        .select("id, title, summary, full_text")
        .is_("sentiment_bert", "null")
        .gte("scraped_at", today)
        .execute()
    )
    return result.data


def predict_sentiment(text: str) -> dict:
    """
    TODO (Burcu): HF Spaces BERT servisine istek at.

    Dönüş: {"sentiment": "pozitif", "score": 0.87}

    Not: Servis URL'i .env'deki BERT_SERVICE_URL değişkeninden okunur.
    """
    # TODO: httpx.post(f"{BERT_SERVICE_URL}/predict", json={"text": text})
    # TODO: Hata durumunda {"sentiment": "nötr", "score": 0.0} döndür
    raise NotImplementedError("Burcu implement edecek — önce HF Spaces servisi hazır olmalı")


def run_bert_scoring():
    """
    Ana fonksiyon — pipeline/run.py bu fonksiyonu çağırır.
    TODO (Burcu): Haberleri al, her biri için predict_sentiment çağır,
    sonuçları Supabase'e yaz.
    """
    if not BERT_SERVICE_URL:
        logger.warning("BERT_SERVICE_URL tanımlı değil, adım atlanıyor.")
        return

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    articles = get_todays_unscored(client)
    logger.info(f"{len(articles)} haber BERT'e gönderilecek")

    # TODO: Her makale için predict_sentiment çağır
    # TODO: articles tablosunu güncelle:
    # client.table("articles").update({
    #     "sentiment_bert": result["sentiment"],
    #     "sentiment_score_bert": result["score"]
    # }).eq("id", article["id"]).execute()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bert_scoring()
