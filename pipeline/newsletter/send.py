"""
pipeline/newsletter/send.py
Sorumlu: Tolunay

Görev:
  Günün sektör özetlerinden HTML bülten oluştur,
  Resend API ile abonelere gönder,
  newsletters tablosuna kayıt yaz.

Çalışma sırası:
  pipeline/run.py tarafından tüm adımlar bittikten sonra çağrılır.

Girdi:
  - Supabase daily_summaries tablosu (bugünün sektör özetleri)
  - Supabase articles tablosu (bugünün haberleri)
  - Supabase subscribers tablosu (aktif aboneler)

Çıktı:
  - Abonelere HTML e-posta gönderilir
  - newsletters tablosuna INSERT

Şablon:
  pipeline/newsletter/templates/bulletin.html
  Değişkenler:
    {{ bugunun_tarihi }}        "29 Haziran 2026"
    {{ sector_summaries }}      daily_summaries listesi
      {{ s.sector }}            sektör adı
      {{ s.headline }}          manşet
      {{ s.bullet_points }}     madde işaretleri
    {{ articles }}              articles listesi
      {{ a.title }}, {{ a.url }}, {{ a.summary }}
      {{ a.image_url }}, {{ a.sector }}, {{ a.author }}
"""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from jinja2 import Environment, FileSystemLoader
import resend

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "bulten@itonews.com")

AYLAR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _format_date(iso_date: str) -> str:
    dt = datetime.fromisoformat(iso_date)
    return f"{dt.day} {AYLAR[dt.month]} {dt.year}"


def get_todays_summaries(client) -> list:
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        client.table("daily_summaries")
        .select("*")
        .eq("summary_date", today)
        .execute()
    )
    return result.data


def get_todays_articles(client) -> list:
    today = datetime.now(timezone.utc).date().isoformat()
    result = (
        client.table("articles")
        .select("*")
        .gte("published_at", today)
        .execute()
    )
    return result.data


def get_active_subscribers(client) -> list:
    result = (
        client.table("subscribers")
        .select("email, name, sectors")
        .eq("is_active", True)
        .execute()
    )
    return result.data


def render_html(summaries: list, articles: list, date: str) -> str:
    env = Environment(loader=FileSystemLoader("pipeline/newsletter/templates"))
    template = env.get_template("bulletin.html")
    return template.render(
        bugunun_tarihi=date,
        sector_summaries=summaries,
        articles=articles
    )


def send_email(to_email: str, subject: str, html: str) -> bool:
    resend.api_key = RESEND_API_KEY
    try:
        r = resend.Emails.send({
            "from": SENDER_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html,
        })
        return r.get("id") is not None
    except Exception as e:
        logger.error(f"E-posta gönderilemedi: {to_email} — {e}")
        return False


def run_newsletter():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    today_iso = datetime.now(timezone.utc).date().isoformat()

    summaries = get_todays_summaries(client)
    if not summaries:
        logger.warning("Bugün için özet yok, bülten gönderilmiyor.")
        return

    articles = get_todays_articles(client)
    date_str = _format_date(today_iso)
    html = render_html(summaries, articles, date_str)

    subscribers = get_active_subscribers(client)
    if not subscribers:
        logger.warning("Aktif abone yok, bülten gönderilmiyor.")
        return

    logger.info(f"{len(subscribers)} aboneye bülten gönderiliyor...")

    success_count = 0
    for sub in subscribers:
        ok = send_email(sub["email"], f"Business News — {date_str}", html)
        if ok:
            success_count += 1

    client.table("newsletters").insert({
        "send_date": today_iso,
        "subject": f"Business News — {date_str}",
        "html_content": html,
        "recipient_count": success_count,
        "status": "sent" if success_count > 0 else "failed",
        "sent_at": datetime.now(timezone.utc).isoformat()
    }).execute()

    logger.info(f"Bülten gönderildi: {success_count}/{len(subscribers)} başarılı")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_newsletter()
