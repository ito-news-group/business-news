"""
pipeline/run.py
Sorumlu: İsmail

Görev:
  Her sabah 06:30'da cron tarafından çalıştırılır.
  Tüm pipeline adımlarını sırayla çağırır.
  Her adımı pipeline_runs tablosuna loglar.

Sıra:
  1. scraper       → haberleri çek, articles'a yaz
  2. process       → sektör + özet belirle (GPT)
  3. daily_summary → sektör bazlı günlük özet (GPT)
  4. bert          → duygu skoru (BERT)
  5. embed         → vektör embedding (RAG)
  6. newsletter    → bülten gönder
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

log_dir = "/app/logs" if os.path.exists("/app") else "./logs"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"{log_dir}/pipeline.log"),
    ]
)
logger = logging.getLogger("pipeline")

from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

from scraper.scraper import run_scraper


def log_run(stage: str, status: str, count: int = 0, error: str = None, duration: float = 0):
    """Pipeline adım logunu Supabase'e yaz"""
    try:
        from supabase import create_client
        client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        client.table("pipeline_runs").insert({
            "run_date": datetime.now(timezone.utc).date().isoformat(),
            "stage": stage,
            "status": status,
            "articles_processed": count,
            "error_message": error,
            "duration_seconds": duration,
        }).execute()
    except Exception as e:
        logger.error(f"Log yazılamadı: {e}")


def run_stage(name: str, fn, *args, **kwargs):
    """Bir pipeline adımını çalıştır, logla, hata varsa yakala"""
    logger.info(f"--- {name} başlıyor ---")
    t0 = datetime.now()
    try:
        result = fn(*args, **kwargs)
        duration = (datetime.now() - t0).total_seconds()
        log_run(name, "success", duration=duration)
        logger.info(f"{name} tamamlandı ({duration:.1f}s)")
        return result
    except NotImplementedError:
        logger.warning(f"{name} henüz implement edilmedi, atlanıyor.")
        log_run(name, "skipped")
    except Exception as e:
        duration = (datetime.now() - t0).total_seconds()
        log_run(name, "failed", error=str(e), duration=duration)
        logger.error(f"{name} hatası: {e}")
        return None


async def main():
    run_date = datetime.now(timezone.utc).date()
    logger.info(f"=== Pipeline başlatıldı: {run_date} ===")

    # 1. Scraper (İsmail)
    count = await run_scraper()
    if count == 0 and count is not None:
        logger.info("Yeni haber yok, pipeline devam ediyor.")

    # 2. Sektör + Özet (Esad)
    from pipeline.gpt.process import run_classification
    run_stage("gpt_process", run_classification)

    # 3. Günlük Sektör Özeti (Esad)
    from pipeline.gpt.daily_sector_summary import run_daily_sector_summary
    run_stage("daily_sector_summary", run_daily_sector_summary)

    # 4. BERT Duygu Skoru (Burcu)
    from pipeline.bert.bert_client import run_bert_scoring
    run_stage("bert_scoring", run_bert_scoring)

    # 5. RAG Embedding (Harun & Kaan)
    from pipeline.rag.embed import run_embedding
    run_stage("rag_embed", run_embedding)

    # 6. Bülten Gönderimi (Tolunay)
    from pipeline.newsletter.send import run_newsletter
    run_stage("newsletter", run_newsletter)

    logger.info(f"=== Pipeline tamamlandı: {run_date} ===")


if __name__ == "__main__":
    asyncio.run(main())