"""
/api/newsletter endpoint'leri
Bülten gönderimi ve abone yönetimi
"""

import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from api.db import get_supabase

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

logger = logging.getLogger(__name__)

router = APIRouter()


class SubscribeRequest(BaseModel):
    email: EmailStr
    name: str = ""
    sectors: list[str] = []   # Boş = tüm sektörler


@router.post("/subscribe")
def subscribe(req: SubscribeRequest):
    """Yeni abone kaydı"""
    client = get_supabase()
    try:
        result = client.table("subscribers").insert({
            "email": req.email,
            "name": req.name,
            "sectors": req.sectors,
            "is_active": True
        }).execute()
        return {"message": "Abonelik başarılı", "email": req.email}
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/unsubscribe/{email}")
def unsubscribe(email: str):
    """Abonelik iptali"""
    client = get_supabase()
    client.table("subscribers").update({"is_active": False}).eq("email", email).execute()
    return {"message": "Abonelik iptal edildi"}


@router.get("/history")
def get_newsletter_history(limit: int = 10):
    """Gönderilen bülten geçmişi"""
    client = get_supabase()
    result = client.table("newsletters").select(
        "id, send_date, subject, recipient_count, status, sent_at"
    ).order("send_date", desc=True).limit(limit).execute()
    return result.data


class TestSendRequest(BaseModel):
    email: EmailStr
    sector: str | None = None


class TestSendByDateRequest(BaseModel):
    email: EmailStr
    date: str
    sector: str | None = None



#mail test kodu 
@router.post("/test-send")
def test_send(req: TestSendRequest):
    """
    Test amaçlı manuel bülten gönderimi.
    Bugünün verileriyle HTML oluşturup belirtilen adrese e-posta gönderir.
    """
    try:
        from pipeline.newsletter.send import (
            get_todays_summaries,
            get_todays_articles,
            render_html,
            send_email,
            _format_date,
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Pipeline modülü bulunamadı: {e}")

    client = get_supabase()
    today_iso = datetime.now(timezone.utc).date().isoformat()

    summaries = get_todays_summaries(client)
    if req.sector:
        summaries = [s for s in summaries if s["sector"] == req.sector]

    articles = client.table("articles").select("*").execute().data
    if req.sector:
        articles = [a for a in articles if a.get("sector") == req.sector]

    if not summaries:
        logger.warning("Bugün için özet bulunamadı, yine de gönderiliyor...")

    date_str = _format_date(today_iso)
    html = render_html(summaries, articles, date_str)

    ok = send_email(
        req.email,
        f"[TEST] Business News — {date_str}" + (f" ({req.sector})" if req.sector else ""),
        html,
    )

    if not ok:
        raise HTTPException(status_code=500, detail="E-posta gönderilemedi")

    return {"message": "Test bülteni gönderildi", "email": req.email}


@router.post("/test-send-by-date")
def test_send_by_date(req: TestSendByDateRequest):
    """
    Belirtilen tarihteki verilerle test bülteni gönderimi.
    Örn: {"email": "...", "date": "2026-06-28", "sector": "diger"}
    """
    try:
        from pipeline.newsletter.send import (
            render_html,
            send_email,
            _format_date,
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Pipeline modülü bulunamadı: {e}")

    client = get_supabase()

    summaries = client.table("daily_summaries").select("*").eq("summary_date", req.date).execute().data
    if req.sector:
        summaries = [s for s in summaries if s["sector"] == req.sector]

    articles = client.table("articles").select("*").execute().data
    if req.sector:
        articles = [a for a in articles if a.get("sector") == req.sector]

    date_str = _format_date(req.date)
    html = render_html(summaries, articles, date_str)

    ok = send_email(
        req.email,
        f"[TEST] Business News — {date_str}" + (f" ({req.sector})" if req.sector else ""),
        html,
    )

    if not ok:
        raise HTTPException(status_code=500, detail="E-posta gönderilemedi")

    return {"message": "Test bülteni gönderildi", "email": req.email, "date": req.date}
