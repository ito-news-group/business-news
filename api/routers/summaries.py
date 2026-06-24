"""
/api/summaries endpoint'leri
Günlük sektör özetleri
"""

from fastapi import APIRouter, Query
from api.db import get_supabase
from datetime import date, datetime, timezone

router = APIRouter()


@router.get("/")
def get_summaries(
    summary_date: date = Query(None, description="Tarih — boş bırakılırsa bugün"),
    sector: str = Query(None)
):
    """Belirli bir güne ait tüm sektör özetlerini döner"""
    if not summary_date:
        summary_date = datetime.now(timezone.utc).date()

    client = get_supabase()
    query = client.table("daily_summaries").select("*").eq("summary_date", summary_date.isoformat())

    if sector:
        query = query.eq("sector", sector)

    result = query.execute()
    return {"date": summary_date.isoformat(), "summaries": result.data}


@router.get("/sentiment-trend")
def get_sentiment_trend(
    sector: str = Query(..., description="Sektör slug'ı"),
    days: int = Query(30, le=90)
):
    """
    Son N günün duygu trendi — grafik için
    Dashboard'daki trend grafiği bu veriyi kullanır
    """
    client = get_supabase()
    result = (
        client.table("daily_summaries")
        .select("summary_date, avg_sentiment, article_count")
        .eq("sector", sector)
        .order("summary_date", desc=True)
        .limit(days)
        .execute()
    )
    return {"sector": sector, "trend": result.data}
