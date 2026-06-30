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
        "id, title, summary, author, published_at, scraped_at, sector, sentiment_gpt, sentiment_bert, image_url, url"
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


@router.get("/paginated")
def get_articles_paginated(
    sector: str = Query(None, description="Sektör slug'ı: 'finans', 'insaat' ..."),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=100)
):
    """Sayfalı haber listesi — frontend pagination için"""
    client = get_supabase()

    def _apply_filters(query):
        query = query.not_.is_("title", "null").neq("title", "")
        query = query.not_.is_("summary", "null").neq("summary", "")
        query = query.not_.is_("sector", "null").neq("sector", "")
        query = query.not_.is_("image_url", "null").neq("image_url", "")
        query = query.not_.is_("url", "null").neq("url", "")
        if sector:
            query = query.eq("sector", sector)
        return query

    count_query = _apply_filters(client.table("articles").select("id", count="exact"))
    total = count_query.execute().count

    data_query = _apply_filters(client.table("articles").select(
        "id, title, summary, author, published_at, scraped_at, sector, sentiment_gpt, sentiment_bert, image_url, url"
    ).order("published_at", desc=True))

    offset = (page - 1) * limit
    data_query = data_query.range(offset, offset + limit - 1)
    result = data_query.execute()

    return {
        "data": result.data,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
    }


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
