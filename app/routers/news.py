from fastapi import APIRouter
from pydantic import BaseModel
from app.core.supabase import supabase
from app.services.news_collector import collect_market_news
from app.services.analyzer import analyze_news_sentiment, analyze_news_batch, check_finbert_health

router = APIRouter()


class AnalyzeRequest(BaseModel):
    headline: str
    summary: str = ""


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


@router.get("/finbert/health")
async def finbert_health():
    """FinBERT 서버 상태 확인"""
    return await check_finbert_health()


@router.post("/analyze")
async def analyze_single(body: AnalyzeRequest):
    """단일 뉴스 감성 분석 (FinBERT)"""
    return await analyze_news_sentiment(body.headline, body.summary)


@router.get("/analyze/latest")
async def analyze_latest(limit: int = 10):
    """최신 뉴스 일괄 병렬 감성 분석 (FinBERT)"""
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
