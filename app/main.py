import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter
from app.routers import news
from app.scheduler import start_scheduler
from app.services import analyzer, translator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await analyzer.init_client()
    start_scheduler()
    yield
    await analyzer.close_client()
    await translator.close_client()


app = FastAPI(title="AI News Curation API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(news.router, prefix="/news", tags=["news"])


@app.get("/health")
async def health():
    return {"status": "ok"}
