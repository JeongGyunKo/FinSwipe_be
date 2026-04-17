import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.limiter import limiter
from app.core.supabase import supabase_admin
from app.routers import news
from app.scheduler import scheduler, start_scheduler
from app.services import analyzer
from app.services.news_collector import close_finlight_client

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


class _SuppressRootPath(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET / HTTP" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(_SuppressRootPath())
logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await analyzer.init_client()
    start_scheduler()
    yield
    # Graceful shutdown
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료 완료")
    await analyzer.close_client()
    await close_finlight_client()
    logger.info("모든 HTTP 클라이언트 종료 완료")


app = FastAPI(title="AI News Curation API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if request.url.path in ("/docs", "/openapi.json", "/redoc"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'"
    return response


app.include_router(news.router, prefix="/news", tags=["news"])


@app.get("/health")
async def health():
    """서버 및 의존 서비스 상태 확인"""
    db_status = "ok"
    try:
        await asyncio.to_thread(
            lambda: supabase_admin.table("news_articles").select("id").limit(1).execute()
        )
    except Exception:
        db_status = "error"

    genai = await analyzer.check_genai_health()

    overall = "ok" if db_status == "ok" and genai["status"] == "ok" else "degraded"
    return {
        "status": overall,
        "db": db_status,
        "genai": genai["status"],
    }
