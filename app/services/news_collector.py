import asyncio
import httpx
from app.core.config import settings
from app.core.supabase import supabase_admin

FINLIGHT_BASE_URL = "https://api.finlight.me"


async def fetch_news_from_finlight(query: str = "stock market finance", page_size: int = 50) -> list:
    """Finlight에서 새 기사만 수집 (단일 API 호출)"""
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
        articles = response.json().get("articles", [])

    # DB에 없는 새 기사만 필터링
    links = [a["link"] for a in articles if a.get("link")]
    new_links = _filter_new_links(links)
    return [a for a in articles if a.get("link") in new_links]


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
        return set(links)


def save_news_to_db(articles: list) -> dict:
    """뉴스 DB 배치 저장 (본문 제외)"""
    if not articles:
        return {"saved": 0, "skipped": 0}

    valid = []
    skipped = 0

    for article in articles:
        if not article.get("link") or not article.get("title"):
            skipped += 1
            continue
        valid.append({
            "headline": article["title"],
            "summary": article.get("summary", ""),
            "source_url": article["link"],
            "categories": article.get("categories", []),
            "countries": article.get("countries", []),
            "is_paywalled": False,
            "published_at": article.get("publishDate"),
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


async def analyze_and_update(articles: list) -> None:
    """백그라운드에서 GenAI 분석 후 DB 업데이트"""
    from app.services.analyzer import analyze_news_batch

    if not articles:
        return

    print(f"[백그라운드] GenAI 분석 시작 → {len(articles)}개")
    enriched = await analyze_news_batch(articles)

    updates = []
    for article in enriched:
        enrichment = article.get("enrichment") or {}
        sentiment = enrichment.get("sentiment")
        if not article.get("link"):
            continue
        updates.append({
            "source_url": article["link"],
            "sentiment_label": sentiment.get("label") if sentiment else None,
            "sentiment_score": sentiment.get("score") if sentiment else None,
            "summary_3lines": enrichment.get("summary_3lines", []),
        })

    for update in updates:
        try:
            supabase_admin.table("news_articles")\
                .update({
                    "sentiment_label": update["sentiment_label"],
                    "sentiment_score": update["sentiment_score"],
                    "summary_3lines": update["summary_3lines"],
                })\
                .eq("source_url", update["source_url"])\
                .execute()
        except Exception as e:
            print(f"[백그라운드] 감성 업데이트 실패 ({update['source_url']}): {e}")

    print(f"[백그라운드] GenAI 분석 완료 → {len(updates)}개 업데이트")


async def collect_market_news():
    """뉴스 수집 파이프라인 - 수집/저장 즉시 반환, 분석은 백그라운드"""
    print("뉴스 수집 시작...")
    new_articles = await fetch_news_from_finlight()

    if not new_articles:
        print("새 기사 없음 - 수집 종료")
        return {"saved": 0, "skipped": 0, "analyzing": 0}

    result = save_news_to_db(new_articles)
    print(f"저장 완료 → {result['saved']}개 저장, {result['skipped']}개 스킵")

    # GenAI 분석은 백그라운드에서 처리 (응답 안 기다림)
    asyncio.create_task(analyze_and_update(new_articles))
    print(f"[백그라운드] GenAI 분석 예약 → {len(new_articles)}개")

    return {**result, "analyzing": len(new_articles)}
