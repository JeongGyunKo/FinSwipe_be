import httpx
from datetime import datetime, timezone
from app.core.config import settings
from app.core.supabase import supabase_admin

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


async def fetch_market_news() -> list:
    """Finnhub에서 일반 시장 뉴스 가져오기"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{FINNHUB_BASE_URL}/news",
            params={"category": "general", "token": settings.finnhub_api_key}
        )
        response.raise_for_status()
        return response.json()


async def fetch_company_news(ticker: str) -> list:
    """특정 종목 뉴스 가져오기"""
    from datetime import date, timedelta
    today = date.today()
    week_ago = today - timedelta(days=7)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{FINNHUB_BASE_URL}/company-news",
            params={
                "symbol": ticker,
                "from": week_ago.isoformat(),
                "to": today.isoformat(),
                "token": settings.finnhub_api_key
            }
        )
        response.raise_for_status()
        return response.json()


def save_news_to_db(articles: list) -> dict:
    """뉴스 DB에 배치 저장 (중복 방지 upsert)"""
    if not articles:
        return {"saved": 0, "skipped": 0}

    valid = []
    skipped = 0

    for article in articles:
        if not article.get("url") or not article.get("headline"):
            skipped += 1
            continue
        valid.append({
            "headline": article.get("headline", ""),
            "summary": article.get("summary", ""),
            "source_url": article["url"],
            "tickers": article.get("related", "").split(",") if article.get("related") else [],
            "is_paywalled": False,
            "published_at": datetime.fromtimestamp(
                article.get("datetime", 0), tz=timezone.utc
            ).isoformat()
        })

    if not valid:
        return {"saved": 0, "skipped": skipped}

    try:
        supabase_admin.table("news_articles").upsert(
            valid,
            on_conflict="source_url"
        ).execute()
        return {"saved": len(valid), "skipped": skipped}
    except Exception as e:
        print(f"배치 저장 실패: {e}")
        return {"saved": 0, "skipped": skipped + len(valid)}


async def collect_market_news():
    """전체 뉴스 수집 파이프라인"""
    print("뉴스 수집 시작...")
    articles = await fetch_market_news()
    result = save_news_to_db(articles)
    print(f"수집 완료 → 저장: {result['saved']}개, 스킵: {result['skipped']}개")
    return result
