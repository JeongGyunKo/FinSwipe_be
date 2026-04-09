from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.routers import news, briefing, portfolio
from app.scheduler import start_scheduler
from app.services import analyzer
from app.services import translator


@asynccontextmanager
async def lifespan(app: FastAPI):
    await analyzer.init_client()
    start_scheduler()
    yield
    await analyzer.close_client()
    await translator.close_client()


app = FastAPI(title="AI News Curation API", lifespan=lifespan)

app.include_router(news.router, prefix="/news", tags=["news"])
app.include_router(briefing.router, prefix="/briefing", tags=["briefing"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])

@app.get("/health")
async def health():
    return {"status": "ok"}
