from fastapi import APIRouter
from api.db import get_supabase

router = APIRouter()

@router.get("/")
def get_sectors():
    """Tüm sektörleri listeler"""
    client = get_supabase()
    result = client.table("sectors").select("*").order("name").execute()
    return result.data
