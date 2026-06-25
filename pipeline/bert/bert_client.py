import os
import logging
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("https://rddnhkxcopwstpflzplj.supabase.co")
SUPABASE_KEY = os.getenv("your_supabase_anon_key_here")
BERT_SERVICE_URL = "https://burcuduzen-turkish-financial-bert-api.hf.space"

def get_todays_unscored(client):
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
    try:
        response = httpx.post(
            f"{BERT_SERVICE_URL}/predict",
            json={"text": text},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        sentiment_map = {"positive": "pozitif", "negative": "negatif", "neutral": "nötr"}
        sentiment = sentiment_map.get(data["sentiment"], "nötr")
        if sentiment == "pozitif":
            score = data["score"]
        elif sentiment == "negatif":
            score = -data["score"]
        else:
            score = 0.0
        return {"sentiment": sentiment, "score": round(score, 4)}
    except Exception as e:
        logger.error(f"BERT servis hatasi: {e}")
        return {"sentiment": "nötr", "score": 0.0}

def run_bert_scoring():
    if not BERT_SERVICE_URL:
        logger.warning("BERT_SERVICE_URL tanimli degil.")
        return
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    articles = get_todays_unscored(client)
    logger.info(f"{len(articles)} haber BERT'e gonderilecek")
    for article in articles:
        text = article.get("summary") or article.get("title") or ""
        if not text:
            continue
        result = predict_sentiment(text)
        client.table("articles").update({
            "sentiment_bert": result["sentiment"],
            "sentiment_score_bert": result["score"]
        }).eq("id", article["id"]).execute()
        logger.info(f"[{article['id']}] {result['sentiment']} ({result['score']})")
    logger.info("BERT skorlama tamamlandi")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bert_scoring()
