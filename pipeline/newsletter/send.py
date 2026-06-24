"""
pipeline/newsletter/send.py
Sorumlu: Tolunay

Görev:
  Günün sektör özetlerinden HTML bülten oluştur,
  Resend API ile abonelere gönder,
  newsletters tablosuna kayıt yaz.

Çalışma sırası:
  pipeline/run.py tarafından tüm adımlar bittikten sonra çağrılır.
  Sabah 06:30'da başlayan pipeline'ın son adımı — 07:00'de bülten gönderilmiş olur.

Girdi:
  - Supabase daily_summaries tablosu (bugünün sektör özetleri)
  - Supabase subscribers tablosu (aktif aboneler)

Çıktı:
  - Abonelere HTML e-posta gönderilir
  - newsletters tablosuna INSERT:
      send_date, subject, html_content, recipient_count, status, sent_at

Şablon:
  Jinja2 ile HTML şablonu oluştur.
  Şablon dosyası: pipeline/newsletter/templates/bulletin.html
  Şablon değişkenleri:
    {{ date }}           bugünün tarihi
    {{ summaries }}      sektör özetleri listesi
      {{ s.sector }}     sektör adı
      {{ s.headline }}   günün en önemli gelişmesi
      {{ s.bullet_points }}  liste olarak bullet'lar
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
# from jinja2 import Environment, FileSystemLoader  # pip install jinja2
# import resend  # pip install resend

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "bulten@itonews.com")


def get_todays_summaries(client) -> list:
    """Bugünün sektör özetlerini getir"""
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        client.table("daily_summaries")
        .select("*")
        .eq("summary_date", today)
        .execute()
    )
    return result.data


def get_active_subscribers(client) -> list:
    """Aktif aboneleri getir"""
    result = (
        client.table("subscribers")
        .select("email, name, sectors")
        .eq("is_active", True)
        .execute()
    )
    return result.data


def render_html(summaries: list, date: str) -> str:
    """
    TODO (Tolunay): Jinja2 ile HTML bülten oluştur.

    pipeline/newsletter/templates/bulletin.html şablonunu kullan.
    Şablonu sen tasarlayacaksın — marka renkleri, logo, düzen serbest.
    """
    # env = Environment(loader=FileSystemLoader("pipeline/newsletter/templates"))
    # template = env.get_template("bulletin.html")
    # return template.render(date=date, summaries=summaries)
    raise NotImplementedError("Tolunay implement edecek")


def send_email(to_email: str, subject: str, html: str) -> bool:
    """
    TODO (Tolunay): Resend API ile e-posta gönder.
    Dönüş: True (başarılı) / False (hata)
    """
    # resend.api_key = RESEND_API_KEY
    # resend.Emails.send({
    #     "from": SENDER_EMAIL,
    #     "to": to_email,
    #     "subject": subject,
    #     "html": html,
    # })
    raise NotImplementedError("Tolunay implement edecek")


def run_newsletter():
    """
    Ana fonksiyon — pipeline/run.py bu fonksiyonu çağırır.
    TODO (Tolunay): Özetleri al, HTML oluştur, abonelere gönder, kayıt yaz.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    today = datetime.now(timezone.utc).date().isoformat()

    summaries = get_todays_summaries(client)
    if not summaries:
        logger.warning("Bugün için özet yok, bülten gönderilmiyor.")
        return

    subscribers = get_active_subscribers(client)
    logger.info(f"{len(subscribers)} aboneye bülten gönderilecek")

    # TODO: render_html ile HTML oluştur
    # TODO: Her abone için send_email çağır
    #   (opsiyonel: abonenin sectors listesi varsa sadece o sektörleri gönder)
    # TODO: newsletters tablosuna kayıt yaz:
    # client.table("newsletters").insert({
    #     "send_date": today,
    #     "subject": f"İTO Haber Bülteni — {today}",
    #     "html_content": html,
    #     "recipient_count": len(subscribers),
    #     "status": "sent",
    #     "sent_at": datetime.now(timezone.utc).isoformat()
    # }).execute()
    raise NotImplementedError("Tolunay implement edecek")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_newsletter()
