"""
/api/newsletter endpoint'leri
Bülten gönderimi ve abone yönetimi
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from api.db import get_supabase

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
