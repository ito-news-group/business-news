"""
Scraper - İstanbul Ticaret Gazetesi
https://istanbulticaretgazetesi.com/son-dakika

Site Next.js tabanlı, lazy-load ile 10'ar haber yüklüyor.
Detay sayfalarında tüm veriler meta tag'lerde mevcut.

Strateji:
  1. Liste sayfasını scroll ederek tüm linkleri topla
  2. Her detay sayfasında meta tag'lerden veri çek
  3. Supabase articles tablosuna yaz
"""

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
from supabase import create_client, Client
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TARGET_URL = os.getenv("SCRAPER_TARGET_URL", "https://istanbulticaretgazetesi.com/son-dakika")
SOURCE_ID = int(os.getenv("SCRAPER_SOURCE_ID", "1"))

MAX_SCROLL_ATTEMPTS = 15
SCROLL_PAUSE = 2.0


def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def make_url_hash(url: str) -> str:
    return hashlib.md5(url.strip().encode()).hexdigest()


def get_existing_hashes(client: Client) -> set:
    result = client.table("articles").select("url_hash").execute()
    return {row["url_hash"] for row in result.data}


async def scroll_to_load_all(page: Page) -> None:
    """Sayfayı scroll ederek lazy-load haberlerin yüklenmesini bekle"""
    previous_count = 0
    stale = 0

    for attempt in range(MAX_SCROLL_ATTEMPTS):
        # Haber linklerini say — site yapısına göre ana içerik linkleri
        links = await page.evaluate("""
            () => document.querySelectorAll('a[href*="istanbulticaretgazetesi.com/"]').length
        """)

        logger.info(f"Scroll {attempt + 1}: {links} link görünüyor")

        if links == previous_count:
            stale += 1
            if stale >= 3:
                logger.info("Yeni içerik gelmiyor, scroll tamamlandı.")
                break
        else:
            stale = 0

        previous_count = links
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(SCROLL_PAUSE)


async def get_article_links(page: Page) -> list:
    """
    Liste sayfasındaki haber URL'lerini topla.
    Site yapısı: her haber /slug formatında, kategori/yazar/galeri sayfaları hariç.
    """
    links = await page.evaluate("""
        () => {
            const base = 'https://istanbulticaretgazetesi.com';
            const exclude = [
                '/son-dakika', '/bugun', '/finans', '/kategori/',
                '/etiket/', '/yazar/', '/galeri', '/video', '/arsiv',
                '/giris', '/iletisim', '/kunye', '/gizlilik', '/finans/borsa'
            ];

            const seen = new Set();
            const results = [];

            document.querySelectorAll('a[href]').forEach(el => {
                const href = el.href || '';
                if (!href.startsWith(base)) return;

                const path = href.replace(base, '');
                if (!path || path === '/') return;

                // Hariç tutulan path'leri atla
                if (exclude.some(ex => path.startsWith(ex))) return;

                // Sadece slug formatındaki haberler (tek seviye path)
                const parts = path.split('/').filter(Boolean);
                if (parts.length !== 1) return;

                // Hash (#) içerenleri atla
                if (href.includes('#')) return;

                if (!seen.has(href)) {
                    seen.add(href);
                    results.push(href);
                }
            });

            return results;
        }
    """)
    return links


async def scrape_article_detail(page: Page, url: str) -> Optional[dict]:
    """
    Detay sayfasından meta tag'leri çek.
    Site Next.js tabanlı — tüm veriler meta tag'lerde mevcut.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(0.8)
    except PlaywrightTimeout:
        logger.warning(f"Timeout: {url}")
        return None
    except Exception as e:
        logger.warning(f"Hata: {url} — {e}")
        return None

    data = await page.evaluate("""
        () => {
            const meta = (name) => {
                const el = document.querySelector(
                    `meta[name="${name}"], meta[property="${name}"]`
                );
                return el ? el.getAttribute('content') : null;
            };

            // Tam metin — Next.js'de genellikle article veya main içinde
            const contentSelectors = [
                'article .prose',
                'article [class*="content"]',
                'main article p',
                '[class*="article-body"]',
                '[class*="post-content"]',
                '[class*="entry-content"]',
                'article p'
            ];

            let fullText = '';
            for (const sel of contentSelectors) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    fullText = Array.from(els).map(e => e.innerText?.trim()).join(' ');
                    if (fullText.length > 100) break;
                }
            }

            // Başlık
            const title = meta('meta-title') ||
                          document.querySelector('h1')?.innerText?.trim() ||
                          document.title?.replace(' — İstanbul Ticaret Gazetesi', '').trim();

            return {
                title,
                summary:     meta('description'),
                imageUrl:    meta('og:image'),
                author:      meta('article:author'),
                publishedAt: meta('article:published_time'),  // ISO format: 2026-06-23T19:49:53+03:00
                section:     meta('article:section'),          // 'Teknoloji', 'Ekonomi' vs.
                fullText:    fullText || ''
            };
        }
    """)

    return data


async def run_scraper() -> int:
    """Ana scraper fonksiyonu — pipeline/run.py tarafından çağrılır"""
    client = get_supabase()
    existing_hashes = get_existing_hashes(client)
    logger.info(f"Veritabanında {len(existing_hashes)} mevcut haber var.")

    new_articles = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800}
        )

        # ADIM 1: Liste sayfasından linkleri topla
        page = await context.new_page()
        logger.info(f"Liste sayfası açılıyor: {TARGET_URL}")

        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        await scroll_to_load_all(page)

        all_links = await get_article_links(page)
        logger.info(f"Toplam {len(all_links)} link bulundu.")

        # Duplicate filtrele
        new_links = [
            url for url in all_links
            if make_url_hash(url) not in existing_hashes
        ]
        logger.info(f"{len(new_links)} yeni haber çekilecek.")

        if not new_links:
            await browser.close()
            return 0

        # ADIM 2: Her haberin detayını çek
        detail_page = await context.new_page()

        for i, url in enumerate(new_links):
            url_hash = make_url_hash(url)
            logger.info(f"[{i+1}/{len(new_links)}] {url}")

            detail = await scrape_article_detail(detail_page, url)
            if not detail or not detail.get("title"):
                logger.warning(f"Veri alınamadı, atlanıyor: {url}")
                continue

            new_articles.append({
                "source_id":    SOURCE_ID,
                "url":          url,
                "url_hash":     url_hash,
                "title":        detail.get("title", ""),
                "summary":      detail.get("summary") or "",
                "full_text":    detail.get("fullText") or "",
                "image_url":    detail.get("imageUrl") or None,
                "author":       detail.get("author") or None,
                "published_at": detail.get("publishedAt") or None,  # zaten ISO format
                "scraped_at":   datetime.now(timezone.utc).isoformat(),
            })

            await asyncio.sleep(1.2)  # Rate limiting

        await browser.close()

    # ADIM 3: Veritabanına yaz
    if new_articles:
        result = client.table("articles").insert(new_articles).execute()
        logger.info(f"{len(new_articles)} haber veritabanına yazıldı.")
    else:
        logger.info("Yazılacak yeni haber yok.")

    return len(new_articles)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s"
    )
    count = asyncio.run(run_scraper())
    print(f"\nTamamlandı: {count} yeni haber eklendi.")