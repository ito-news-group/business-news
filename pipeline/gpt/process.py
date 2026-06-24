"""
pipeline/gpt/process.py
Sorumlu: Esad

Görev:
  Bugün scraper'ın çektiği haberleri GPT-4o-mini'ye göndererek
  tek bir API çağrısında hem sektörü hem de 3 bullet point özeti al.
  Sonuçları articles tablosuna yaz.

Çalışma sırası:
  pipeline/run.py tarafından scraper'dan sonra çağrılır.

Girdi:
  Supabase articles tablosu — sector IS NULL olan bugünün kayıtları

Çıktı:
  articles tablosu güncellenir:
    - sector      : str  ('finans', 'insaat', ...)
    - summary     : str  ('• ...\n• ...\n• ...')

Kullanılacak kütüphaneler:
  pip install openai supabase python-dotenv
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

SECTORS = [
    "insaat", "finans", "tekstil", "teknoloji", "enerji",
    "tarim", "ihracat", "lojistik", "turizm", "saglik",
    "egitim", "perakende", "otomotiv", "gayrimenkul", "diger"
]

# TODO (Esad): Bu prompt'u geliştir, örnekler ekle
PROMPT_TEMPLATE = """
Aşağıdaki haber başlığı ve metnine göre:

1. Sektör: {sectors} listesinden sadece birini seç (slug olarak döndür)
2. Özet: 3 bullet point halinde özetle. Her madde "• " ile başlasın.

Başlık: {title}
Metin: {text}

Sadece JSON döndür, başka hiçbir şey yazma:
{{"sector": "...", "summary": "• ...\n• ...\n• ..."}}
"""


def get_todays_unprocessed(client):
    """Bugün çekilmiş, henüz sınıflandırılmamış haberleri getir"""
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        client.table("articles")
        .select("id, title, full_text, summary")
        .is_("sector", "null")
        .gte("scraped_at", today)
        .execute()
    )
    return result.data


def process_article(article: dict, openai_client) -> dict:
    """
    TODO (Esad): Bu fonksiyonu implement et.

    Tek bir makale için GPT-4o-mini'ye istek at,
    sektör ve özet döndür.

    Dönüş: {"sector": "finans", "summary": "• ...\n• ...\n• ..."}
    """
    # TODO: openai_client.chat.completions.create(...) çağrısı yap
    # TODO: JSON yanıtı parse et
    # TODO: Hata durumunda {"sector": "diger", "summary": ""} döndür
    raise NotImplementedError("Esad implement edecek")


def run_classification():
    """
    Ana fonksiyon — pipeline/run.py bu fonksiyonu çağırır.
    TODO (Esad): get_todays_unprocessed ile haberleri al,
    her biri için process_article çağır,
    sonuçları Supabase'e yaz.
    """
    # TODO: OpenAI client oluştur
    # TODO: Supabase client oluştur
    # TODO: Haberleri al, işle, güncelle
    # Örnek güncelleme:
    # client.table("articles").update({
    #     "sector": result["sector"],
    #     "summary": result["summary"]
    # }).eq("id", article["id"]).execute()
    raise NotImplementedError("Esad implement edecek")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_classification()
