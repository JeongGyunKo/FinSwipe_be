import asyncio
import httpx
from app.core.config import settings

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("GenAI 클라이언트가 초기화되지 않았습니다")
    return _client


async def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.genai_url,
        auth=(settings.genai_user, settings.genai_password),
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def check_genai_health() -> dict:
    try:
        response = await get_client().get("/health")
        if response.status_code == 200:
            return {"status": "ok"}
        if response.status_code == 503:
            return {"status": "suspended", "reason": "서버 일시 중단"}
        return {"status": "error", "code": response.status_code}
    except httpx.ConnectError:
        return {"status": "offline", "reason": "연결 불가 (서버 꺼짐)"}
    except httpx.TimeoutException:
        return {"status": "offline", "reason": "응답 시간 초과"}
    except Exception as e:
        return {"status": "offline", "reason": str(e)}


async def submit_article(
    news_id: str,
    title: str,
    link: str,
    article_text: str | None = None,
    summary_text: str | None = None,
    tickers: list[str] | None = None,
) -> bool:
    """기사를 GenAI 큐에 제출. 성공 시 True."""
    try:
        news_id = news_id.rstrip("/")
        link = link.rstrip("/")
        payload: dict = {"news_id": news_id, "title": title, "link": link}
        if article_text:
            payload["article_text"] = article_text
        if summary_text:
            payload["summary_text"] = summary_text
        if tickers:
            payload["ticker"] = tickers

        resp = await get_client().post("/api/v1/articles/enrich-text", json=payload)
        return resp.status_code in (200, 202)
    except Exception as e:
        print(f"[GenAI] 제출 실패: {news_id[:60]} | {e}")
        return False


def _parse_storage_payload(enrichment: dict) -> dict:
    """EnrichmentStoragePayload → 우리 포맷으로 변환 (process-next 응답에서 직접)"""
    sentiment_raw = enrichment.get("sentiment") or {}
    sentiment = None
    if sentiment_raw.get("label"):
        sentiment = {
            "label": sentiment_raw.get("label"),
            "score": sentiment_raw.get("score"),
            "confidence": sentiment_raw.get("confidence"),
        }

    summary_3lines = [
        s.get("text") for s in enrichment.get("summary_3lines", [])
        if isinstance(s, dict) and s.get("text")
    ]

    mixed = enrichment.get("article_mixed") or {}
    xai = enrichment.get("xai") or None

    return {
        "status": enrichment.get("analysis_status"),
        "outcome": enrichment.get("analysis_outcome"),
        "sentiment": sentiment,
        "summary_3lines": summary_3lines,
        "is_mixed": mixed.get("is_mixed"),
        "xai": xai,
        "error": None,
    }


def _unavailable(reason: str) -> dict:
    return {
        "status": "unavailable",
        "outcome": "fatal_failure",
        "sentiment": None,
        "summary_3lines": [],
        "is_mixed": None,
        "error": {"code": "server_unavailable", "message": reason},
    }


async def analyze_news_batch(articles: list[dict]) -> list[dict]:
    """기사 제출 → process-next로 큐 소진 → 응답에서 직접 결과 수집"""
    valid = [
        a for a in articles
        if (a.get("link") or a.get("source_url") or "").startswith("http")
    ]

    # 제출
    submitted_map: dict[str, dict] = {}  # normalized news_id → article
    for a in valid:
        link = (a.get("link") or a.get("source_url") or "").rstrip("/")
        ok = await submit_article(
            news_id=link,
            title=a.get("title") or a.get("headline") or "",
            link=link,
            article_text=(a.get("content") or "").strip() or None,
            summary_text=(a.get("summary") or "").strip() or None,
            tickers=a.get("tickers") or None,
        )
        if ok:
            submitted_map[link] = a

    print(f"[GenAI] 제출 완료 {len(submitted_map)}개, 큐 처리 시작...")

    # process-next 응답에서 직접 결과 수집 (fetch_result 불필요)
    results: dict[str, dict] = {}
    remaining = set(submitted_map.keys())

    for i in range(10000):
        try:
            resp = await get_client().post("/api/v1/jobs/process-next")
            data = resp.json()
            if not data.get("processed", False):
                print(f"[GenAI] 큐 소진 (총 {i}개 처리)")
                break

            p_id = (data.get("news_id") or "").rstrip("/")
            p_outcome = data.get("analysis_outcome")
            enrichment = data.get("enrichment")

            if p_id in remaining:
                remaining.discard(p_id)
                if enrichment and p_outcome in ("success", "partial_success"):
                    results[p_id] = _parse_storage_payload(enrichment)
                    xai_keys = list(enrichment.get("xai", {}).keys()) if isinstance(enrichment.get("xai"), dict) else enrichment.get("xai")
                    print(f"[GenAI] 결과 수집: {p_id[:60]} outcome={p_outcome} xai={xai_keys}")
                else:
                    results[p_id] = _unavailable(f"처리 실패: {p_outcome}")
                    print(f"[GenAI] 실패: {p_id[:60]} outcome={p_outcome}")

                if not remaining:
                    print(f"[GenAI] 목표 기사 전부 완료 (총 {i+1}개 처리)")
                    break
        except Exception as e:
            print(f"[GenAI] process-next 오류: {e}")
            break

    # 결과 미수집 기사 처리
    output = []
    for a in valid:
        link = (a.get("link") or a.get("source_url") or "").rstrip("/")
        result = results.get(link) or _unavailable("결과 없음")
        output.append({**a, "enrichment": result})

    return output
