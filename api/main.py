"""
FastAPI Ana Uygulama
Tüm endpoint'leri barındırır.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.routers import articles, summaries, sectors, rag, newsletter, health

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API başlatılıyor")
    yield
    logger.info("API kapatılıyor")


app = FastAPI(
    title="İTO News API",
    description="İstanbul Ticaret Gazetesi haber otomasyonu API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS — React frontend için
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production'da Vercel URL'ini yaz
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router'ları bağla
app.include_router(health.router, tags=["Health"])
app.include_router(articles.router, prefix="/api/articles", tags=["Articles"])
app.include_router(summaries.router, prefix="/api/summaries", tags=["Summaries"])
app.include_router(sectors.router, prefix="/api/sectors", tags=["Sectors"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG"])
app.include_router(newsletter.router, prefix="/api/newsletter", tags=["Newsletter"])
