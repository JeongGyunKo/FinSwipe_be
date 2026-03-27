import asyncio
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.supabase import supabase_admin as supabase
from app.services.news_collector import collect_market_news, analyze_and_update
from app.services.analyzer import enrich_article, analyze_news_batch, check_genai_health

router = APIRouter()


class AnalyzeRequest(BaseModel):
    news_id: str
    headline: str
    source_url: str
    content: str = ""
    tickers: list[str] = []
    published_at: str = ""


@router.get("/test")
async def test_supabase():
    result = supabase.table("news_articles").select("*").limit(5).execute()
    return {
        "status": "ok",
        "count": len(result.data),
        "data": result.data
    }


@router.post("/collect")
async def collect_news():
    """뉴스 수집 트리거 (수동)"""
    result = await collect_market_news()
    return result


@router.get("/latest")
async def get_latest_news(limit: int = 20):
    """최신 뉴스 조회"""
    result = supabase.table("news_articles")\
        .select("*")\
        .order("published_at", desc=True)\
        .limit(limit)\
        .execute()
    return {
        "count": len(result.data),
        "data": result.data
    }


@router.get("/genai/health")
async def genai_health():
    """GenAI 서버 상태 확인"""
    return await check_genai_health()


@router.post("/analyze")
async def analyze_single(body: AnalyzeRequest):
    """단일 뉴스 분석 (GenAI 서버 - 요약 + 감성 + XAI)"""
    return await enrich_article(
        news_id=body.news_id,
        title=body.headline,
        link=body.source_url,
        content=body.content or None,
        tickers=body.tickers or None,
        published_at=body.published_at or None,
    )


@router.get("/analyze/latest")
async def analyze_latest(limit: int = 10):
    """최신 뉴스 일괄 병렬 분석 (GenAI)"""
    result = supabase.table("news_articles")\
        .select("*")\
        .order("published_at", desc=True)\
        .limit(limit)\
        .execute()
    analyzed = await analyze_news_batch(result.data)
    return {
        "count": len(analyzed),
        "data": analyzed
    }


@router.post("/reanalyze")
async def reanalyze_pending(limit: int = 50):
    """미분석 기사 백그라운드 재분석 (sentiment/summary가 없는 기사)"""
    result = supabase.table("news_articles")\
        .select("id,headline,summary,source_url,content,published_at")\
        .is_("sentiment_label", "null")\
        .order("published_at", desc=True)\
        .limit(limit)\
        .execute()

    articles = [
        {
            "title": a["headline"],
            "link": a["source_url"],
            "source_url": a["source_url"],
            "content": a.get("content"),
            "summary": a.get("summary", ""),
            "published_at": a.get("published_at"),
        }
        for a in result.data
    ]

    if not articles:
        return {"message": "미분석 기사 없음", "count": 0}

    task = asyncio.create_task(analyze_and_update(articles))
    task.add_done_callback(
        lambda t: print(f"[재분석] 오류: {t.exception()}") if t.exception() else None
    )
    return {"message": "백그라운드 재분석 시작", "count": len(articles)}
