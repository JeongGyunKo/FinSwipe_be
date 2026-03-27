import asyncio
import httpx
from app.core.config import settings
from app.core.supabase import supabase_admin

FINLIGHT_BASE_URL = "https://api.finlight.me"

# Finlight 전용 클라이언트 (연결 풀 재사용)
_finlight_client: httpx.AsyncClient | None = None


def get_finlight_client() -> httpx.AsyncClient:
    global _finlight_client
    if _finlight_client is None:
        _finlight_client = httpx.AsyncClient(
            base_url=FINLIGHT_BASE_URL,
            headers={"X-API-KEY": settings.finlight_api_key},
            timeout=20.0,
        )
    return _finlight_client


async def fetch_news_from_finlight(query: str = "stock market finance", page_size: int = 50) -> list[dict]:
    """Finlight에서 새 기사만 수집"""
    try:
        response = await get_finlight_client().post(
            "/v2/articles",
            json={
                "query": query,
                "language": "en",
                "pageSize": page_size,
                "includeContent": True,
            }
        )
        response.raise_for_status()
        articles = response.json().get("articles", [])
    except httpx.HTTPStatusError as e:
        print(f"[Finlight 오류] HTTP {e.response.status_code}: {e.response.text[:200]}")
        return []
    except httpx.TimeoutException:
        print("[Finlight 오류] 응답 시간 초과")
        return []
    except httpx.ConnectError as e:
        print(f"[Finlight 오류] 연결 실패: {e}")
        return []
    except Exception as e:
        print(f"[Finlight 오류] {type(e).__name__}: {e}")
        return []

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


def save_news_to_db(articles: list[dict]) -> dict:
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
            "content": article.get("content") or None,
            "categories": article.get("categories", []),
            "countries": article.get("countries", []),
            "is_paywalled": False,
            "published_at": article.get("publishDate"),
        })

    if not valid:
        return {"saved": 0, "skipped": skipped}

    try:
        # ignore_duplicates=True: 이미 존재하는 기사는 완전히 스킵 (분석 데이터 보호)
        supabase_admin.table("news_articles").upsert(
            valid, on_conflict="source_url", ignore_duplicates=True
        ).execute()
        return {"saved": len(valid), "skipped": skipped}
    except Exception as e:
        print(f"배치 저장 실패: {e}")
        return {"saved": 0, "skipped": skipped + len(valid)}


async def analyze_and_update(articles: list[dict]) -> None:
    """백그라운드에서 GenAI 분석 후 DB 업데이트"""
    from app.services.analyzer import analyze_news_batch

    if not articles:
        return

    try:
        print(f"[백그라운드] GenAI 분석 시작 → {len(articles)}개")
        enriched = await analyze_news_batch(articles)

        updates = []
        for article in enriched:
            enrichment = article.get("enrichment") or {}
            sentiment = enrichment.get("sentiment")
            link = article.get("link") or article.get("source_url")
            if not link:
                continue
            updates.append({
                "source_url": link,
                "sentiment_label": sentiment.get("label") if isinstance(sentiment, dict) else None,
                "sentiment_score": sentiment.get("score") if isinstance(sentiment, dict) else None,
                "summary_3lines": enrichment.get("summary_3lines", []),
            })

        # 개별 update (upsert는 headline NOT NULL 제약 위반으로 실패)
        failed = 0
        for u in updates:
            try:
                supabase_admin.table("news_articles").update({
                    "sentiment_label": u["sentiment_label"],
                    "sentiment_score": u["sentiment_score"],
                    "summary_3lines": u["summary_3lines"],
                }).eq("source_url", u["source_url"]).execute()
            except Exception as e:
                failed += 1
                print(f"[백그라운드] 업데이트 실패 ({u['source_url'][:50]}): {e}")
        if failed:
            print(f"[백그라운드] {failed}개 업데이트 실패")

        print(f"[백그라운드] GenAI 분석 완료 → {len(updates)}개 업데이트")

    except Exception as e:
        print(f"[백그라운드] 분석 파이프라인 오류: {type(e).__name__}: {e}")


def cleanup_old_content() -> None:
    """24시간 지난 기사 원문 삭제 (요약본은 유지)"""
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        result = supabase_admin.table("news_articles")\
            .update({"content": None})\
            .lt("created_at", cutoff)\
            .not_.is_("content", "null")\
            .execute()
        print(f"[정리] 24시간 이상 된 원문 삭제 완료")
    except Exception as e:
        print(f"[정리] 원문 삭제 실패: {e}")


async def collect_market_news() -> dict:
    """뉴스 수집 파이프라인 - 수집/저장 즉시 반환, 분석은 백그라운드"""
    print("뉴스 수집 시작...")
    new_articles = await fetch_news_from_finlight()

    if not new_articles:
        print("새 기사 없음 - 수집 종료")
        return {"saved": 0, "skipped": 0, "analyzing": 0}

    result = save_news_to_db(new_articles)
    print(f"저장 완료 → {result['saved']}개 저장, {result['skipped']}개 스킵")

    if result["saved"] > 0:
        task = asyncio.create_task(analyze_and_update(new_articles))
        task.add_done_callback(
            lambda t: print(f"[백그라운드] 태스크 오류: {t.exception()}") if t.exception() else None
        )
        print(f"[백그라운드] GenAI 분석 예약 → {len(new_articles)}개")

    return {**result, "analyzing": len(new_articles) if result["saved"] > 0 else 0}
