"""
FastAPI Ana Uygulama
Tüm endpoint'leri barındırır.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path

from api.routers import articles, summaries, sectors, rag, newsletter, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uygulama başlarken
    print("API başlatılıyor...")
    yield
    # Uygulama kapanırken
    print("API kapatılıyor...")


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
@app.get("/test-rag", include_in_schema=False)
def serve_rag_test_page():
    return FileResponse(Path(__file__).resolve().parent.parent / "templates" / "rag_test.html")

app.include_router(health.router, tags=["Health"])
app.include_router(articles.router, prefix="/api/articles", tags=["Articles"])
app.include_router(summaries.router, prefix="/api/summaries", tags=["Summaries"])
app.include_router(sectors.router, prefix="/api/sectors", tags=["Sectors"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG"])
app.include_router(newsletter.router, prefix="/api/newsletter", tags=["Newsletter"])
