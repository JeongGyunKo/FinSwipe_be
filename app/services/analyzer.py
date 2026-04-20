import asyncio
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)
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
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
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
    """diagnose 엔드포인트 전용 — 제출만 하고 bool 반환"""
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
        logger.error(f"[GenAI] 제출 실패: {news_id[:60]} | {e}")
        return False


def _parse_direct_response(data: dict) -> dict:
    """enrich-text 직접 응답 파싱 (status/outcome 필드)"""
    sentiment_raw = data.get("sentiment") or {}
    sentiment = None
    if sentiment_raw.get("label"):
        sentiment = {
            "label": sentiment_raw.get("label"),
            "score": sentiment_raw.get("score"),
            "confidence": sentiment_raw.get("confidence"),
        }

    logger.debug(
        f"[파싱] sentiment_raw={sentiment_raw} → parsed={sentiment} | "
        f"status={data.get('status')} outcome={data.get('outcome')} | "
        f"summary_3lines_count={len(data.get('summary_3lines') or [])} "
        f"xai={'있음' if data.get('xai') else '없음'} "
        f"stage_statuses={data.get('stage_statuses')} "
        f"error={data.get('error')}"
    )

    raw_summary = data.get("summary_3lines") or []
    summary_3lines = []
    for s in raw_summary:
        if isinstance(s, str):
            summary_3lines.append(s)
        elif isinstance(s, dict):
            summary_3lines.append(s.get("text") or s.get("line") or s.get("content") or "")

    mixed_flags = data.get("mixed_flags") or {}
    xai = data.get("xai") or None

    localized = data.get("localized") or {}
    raw_summary_ko = localized.get("summary_3lines") or []
    summary_3lines_ko = []
    for s in raw_summary_ko:
        if isinstance(s, str):
            summary_3lines_ko.append(s)
        elif isinstance(s, dict):
            summary_3lines_ko.append(s.get("text") or s.get("line") or s.get("content") or "")

    return {
        "status": data.get("status"),
        "outcome": data.get("outcome"),
        "sentiment": sentiment,
        "summary_3lines": summary_3lines,
        "is_mixed": mixed_flags.get("is_mixed"),
        "xai": xai,
        "error": data.get("error"),
        "headline_ko": localized.get("title") or None,
        "summary_3lines_ko": summary_3lines_ko or None,
        "xai_ko": localized.get("xai") or None,
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


_SUBMIT_SEMAPHORE = asyncio.Semaphore(2)


async def analyze_news_batch(articles: list[dict]) -> list[dict]:
    """기사 병렬 enrichment (최대 5개 동시) → enrich-text 응답에서 직접 결과 수집"""
    valid = [
        a for a in articles
        if (a.get("link") or a.get("source_url") or "").startswith("http")
    ]

    async def _enrich_one(a: dict) -> tuple[str, dict]:
        link = (a.get("link") or a.get("source_url") or "").rstrip("/")
        async with _SUBMIT_SEMAPHORE:
            try:
                article_text = (a.get("content") or "").strip() or None
                if not article_text:
                    logger.warning(f"[GenAI] 원문 없음 → 스킵: {link[:60]}")
                    return (link, _unavailable("원문 없음"))

                tickers = a.get("tickers") or None
                payload: dict = {
                    "news_id": link,
                    "title": a.get("title") or a.get("headline") or "",
                    "link": link,
                    "article_text": article_text,
                }
                if tickers:
                    payload["ticker"] = tickers

                resp = await get_client().post("/api/v1/articles/enrich-text", json=payload)
                if resp.status_code not in (200, 202):
                    logger.warning(f"[GenAI] enrich-text 실패: {link[:60]} status={resp.status_code}")
                    return (link, _unavailable(f"HTTP {resp.status_code}"))

                data = resp.json()
                outcome = data.get("outcome") or ""
                parsed = _parse_direct_response(data)

                if outcome in ("success", "partial_success"):
                    logger.info(
                        f"[GenAI] 결과 수집: {link[:60]} outcome={outcome} | "
                        f"sentiment={parsed.get('sentiment')} "
                        f"summary_lines={len(parsed.get('summary_3lines') or [])} "
                        f"xai={'있음' if parsed.get('xai') else '없음'}"
                    )
                else:
                    logger.warning(
                        f"[GenAI] 분석 실패: {link[:60]} outcome={outcome} | "
                        f"stage_statuses={data.get('stage_statuses')} error={data.get('error')}"
                    )
                return (link, parsed)

            except Exception as e:
                logger.error(f"[GenAI] enrich-text 오류: {link[:60]} | {e}")
                return (link, _unavailable(str(e)))

    logger.info(f"[GenAI] enrichment 시작 → {len(valid)}개 (최대 5개 동시)")
    results_list = await asyncio.gather(*[_enrich_one(a) for a in valid])
    results = dict(results_list)

    output = []
    for a in valid:
        link = (a.get("link") or a.get("source_url") or "").rstrip("/")
        result = results.get(link) or _unavailable("결과 없음")
        output.append({**a, "enrichment": result})

    return output
