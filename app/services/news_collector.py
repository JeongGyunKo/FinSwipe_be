import httpx
from app.core.config import settings
from app.core.supabase import supabase_admin

FINLIGHT_BASE_URL = "https://api.finlight.me"


async def fetch_news_from_finlight(query: str = "stock market finance", page_size: int = 50) -> list:
    """Finlight에서 뉴스 + 본문 수집"""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{FINLIGHT_BASE_URL}/v2/articles",
            headers={"X-API-KEY": settings.finlight_api_key},
            json={
                "query": query,
                "language": "en",
                "pageSize": page_size,
                "includeContent": True,
            }
        )
        response.raise_for_status()
        data = response.json()
        return data.get("articles", [])


def save_news_to_db(articles: list) -> dict:
    """뉴스 DB 배치 저장 (본문 제외, 분석 결과 포함)"""
    if not articles:
        return {"saved": 0, "skipped": 0}

    valid = []
    skipped = 0

    for article in articles:
        if not article.get("link") or not article.get("title"):
            skipped += 1
            continue

        enrichment = article.get("enrichment") or {}
        sentiment = enrichment.get("sentiment")

        valid.append({
            "headline": article["title"],
            "summary": article.get("summary", ""),
            "source_url": article["link"],
            "categories": article.get("categories", []),
            "countries": article.get("countries", []),
            "is_paywalled": False,
            "published_at": article.get("publishDate"),
            "sentiment_label": sentiment.get("label") if sentiment else None,
            "sentiment_score": sentiment.get("score") if sentiment else None,
            "summary_3lines": enrichment.get("summary_3lines", []),
        })

    if not valid:
        return {"saved": 0, "skipped": skipped}

    try:
        supabase_admin.table("news_articles").upsert(
            valid, on_conflict="source_url"
        ).execute()
        return {"saved": len(valid), "skipped": skipped}
    except Exception as e:
        print(f"배치 저장 실패: {e}")
        return {"saved": 0, "skipped": skipped + len(valid)}


async def collect_market_news():
    """전체 뉴스 수집 파이프라인 (Finlight → GenAI 분석 → DB 저장)"""
    from app.services.analyzer import analyze_news_batch

    print("뉴스 수집 시작...")
    articles = await fetch_news_from_finlight()
    print(f"Finlight에서 {len(articles)}개 기사 수집")

    enriched = await analyze_news_batch(articles)

    result = save_news_to_db(enriched)
    print(f"수집 완료 → 저장: {result['saved']}개, 스킵: {result['skipped']}개")
    return result
