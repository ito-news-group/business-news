"""
/api/articles endpoint'leri
React frontend bu endpoint'leri kullanır.
"""

from fastapi import APIRouter, Query, HTTPException
from api.db import get_supabase
from datetime import date

router = APIRouter()


@router.get("/")
def get_articles(
    sector: str = Query(None, description="Sektör filtresi: 'finans', 'insaat' ..."),
    date_from: date = Query(None, description="Başlangıç tarihi: 2025-06-01"),
    date_to: date = Query(None, description="Bitiş tarihi: 2025-06-22"),
    limit: int = Query(20, le=100),
    offset: int = Query(0)
):
    """Haberleri filtreli listeler"""
    client = get_supabase()
    query = client.table("articles").select(
        "id, title, summary, author, published_at, sector, sentiment_gpt, sentiment_bert, url"
    ).order("published_at", desc=True)

    if sector:
        query = query.eq("sector", sector)
    if date_from:
        query = query.gte("published_at", date_from.isoformat())
    if date_to:
        query = query.lte("published_at", date_to.isoformat())

    query = query.range(offset, offset + limit - 1)
    result = query.execute()
    return {"data": result.data, "count": len(result.data)}


@router.get("/{article_id}")
def get_article(article_id: int):
    """Tek haber detayı"""
    client = get_supabase()
    result = client.table("articles").select("*").eq("id", article_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Haber bulunamadı")
    return result.data


@router.get("/today/count")
def today_article_count():
    """Bugün çekilen haber sayısı — dashboard için"""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    client = get_supabase()
    result = client.table("articles").select("id", count="exact").gte("scraped_at", today).execute()
    return {"date": today, "count": result.count}
