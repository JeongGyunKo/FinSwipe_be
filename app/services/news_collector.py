import httpx
from app.core.config import settings
from app.core.supabase import supabase_admin

FINLIGHT_BASE_URL = "https://api.finlight.me"


async def fetch_news_from_finlight(query: str = "stock market finance", page_size: int = 50) -> list:
    """Finlight에서 뉴스 수집 (새 기사는 본문 포함)"""
    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1단계: 본문 없이 빠르게 목록 수집
        response = await client.post(
            f"{FINLIGHT_BASE_URL}/v2/articles",
            headers={"X-API-KEY": settings.finlight_api_key},
            json={
                "query": query,
                "language": "en",
                "pageSize": page_size,
            }
        )
        response.raise_for_status()
        articles = response.json().get("articles", [])

        # 2단계: DB에 없는 새 기사만 필터링
        links = [a["link"] for a in articles if a.get("link")]
        new_links = _filter_new_links(links)

        if not new_links:
            return []

        new_articles = [a for a in articles if a.get("link") in new_links]

        # 3단계: 새 기사만 본문 포함해서 다시 수집
        response2 = await client.post(
            f"{FINLIGHT_BASE_URL}/v2/articles",
            headers={"X-API-KEY": settings.finlight_api_key},
            json={
                "query": query,
                "language": "en",
                "pageSize": page_size,
                "includeContent": True,
            }
        )
        response2.raise_for_status()
        all_with_content = response2.json().get("articles", [])

        # 새 기사만 반환 (본문 포함)
        content_map = {a["link"]: a for a in all_with_content if a.get("link")}
        return [content_map[link] for link in new_links if link in content_map]


def _filter_new_links(links: list[str]) -> set[str]:
    """DB에 없는 링크만 반환"""
    if not links:
        return set()
    try:
        result = supabase_admin.table("news_articles")\
            .select("source_url")\
            .in_("source_url", links)\
            .execute()
        existing = {row["source_url"] for row in result.data}
        return set(links) - existing
    except Exception as e:
        print(f"기존 기사 조회 실패: {e}")
        return set(links)  # 실패 시 전부 새 기사로 처리


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
    """전체 뉴스 수집 파이프라인 (Finlight → 새 기사만 GenAI 분석 → DB 저장)"""
    from app.services.analyzer import analyze_news_batch

    print("뉴스 수집 시작...")
    new_articles = await fetch_news_from_finlight()

    if not new_articles:
        print("새 기사 없음 - 수집 종료")
        return {"saved": 0, "skipped": 0}

    print(f"새 기사 {len(new_articles)}개 → GenAI 분석 시작")
    enriched = await analyze_news_batch(new_articles)

    result = save_news_to_db(enriched)
    print(f"수집 완료 → 저장: {result['saved']}개, 스킵: {result['skipped']}개")
    return result
