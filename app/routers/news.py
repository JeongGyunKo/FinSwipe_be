from fastapi import APIRouter
from app.core.supabase import supabase
from app.services.news_collector import collect_market_news

router = APIRouter()

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