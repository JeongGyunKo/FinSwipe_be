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


def _parse_storage_payload(enrichment: dict) -> dict:
    sentiment_raw = enrichment.get("sentiment") or {}
    sentiment = None
    if sentiment_raw.get("label"):
        sentiment = {
            "label": sentiment_raw.get("label"),
            "score": sentiment_raw.get("score"),
            "confidence": sentiment_raw.get("confidence"),
        }

    raw_summary = enrichment.get("summary_3lines") or []
    summary_3lines = []
    for s in raw_summary:
        if isinstance(s, str):
            summary_3lines.append(s)
        elif isinstance(s, dict):
            summary_3lines.append(s.get("text") or s.get("line") or s.get("content") or "")

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


_SUBMIT_SEMAPHORE = asyncio.Semaphore(5)


async def _submit_one(a: dict) -> tuple[str, dict] | None:
    """단일 기사 제출 → (link, article) 반환. 실패 시 None."""
    link = (a.get("link") or a.get("source_url") or "").rstrip("/")
    async with _SUBMIT_SEMAPHORE:
        ok = await submit_article(
            news_id=link,
            title=a.get("title") or a.get("headline") or "",
            link=link,
            article_text=(a.get("content") or "").strip() or None,
            summary_text=(a.get("summary") or "").strip() or None,
            tickers=a.get("tickers") or None,
        )
    return (link, a) if ok else None


async def analyze_news_batch(articles: list[dict]) -> list[dict]:
    """기사 병렬 제출(최대 5개 동시) → process-next로 큐 소진 → 응답에서 직접 결과 수집"""
    valid = [
        a for a in articles
        if (a.get("link") or a.get("source_url") or "").startswith("http")
    ]

    submit_results = await asyncio.gather(*[_submit_one(a) for a in valid])
    submitted_map: dict[str, dict] = {
        link: a for link, a in (r for r in submit_results if r is not None)
    }

    logger.info(f"[GenAI] 제출 완료 {len(submitted_map)}개, 큐 처리 시작...")

    results: dict[str, dict] = {}
    remaining = set(submitted_map.keys())

    for i in range(500):
        try:
            resp = await get_client().post("/api/v1/jobs/process-next")
            data = resp.json()
            if not data.get("processed", False):
                logger.info(f"[GenAI] 큐 소진 (총 {i}개 처리)")
                break

            p_id = (data.get("news_id") or "").rstrip("/")
            p_outcome = data.get("analysis_outcome")
            enrichment = data.get("enrichment")

            if p_id not in remaining:
                logger.debug(f"[GenAI] 큐에서 처리됐지만 우리 목록에 없음: {p_id[:80]}")

            if p_id in remaining:
                remaining.discard(p_id)
                if enrichment and p_outcome in ("success", "partial_success"):
                    results[p_id] = _parse_storage_payload(enrichment)
                    logger.info(f"[GenAI] 결과 수집: {p_id[:60]} outcome={p_outcome}")
                else:
                    results[p_id] = _unavailable(f"처리 실패: {p_outcome}")
                    logger.warning(f"[GenAI] 실패: {p_id[:60]} outcome={p_outcome}")
                    if enrichment:
                        logger.debug(f"  ↳ stage_statuses={enrichment.get('stage_statuses')} errors={enrichment.get('errors')}")

                if not remaining:
                    logger.info(f"[GenAI] 목표 기사 전부 완료 (총 {i+1}개 처리)")
                    break
        except Exception as e:
            logger.error(f"[GenAI] process-next 오류: {e}")
            break

    if remaining:
        logger.warning(f"[GenAI] 큐 소진 후 미처리 {len(remaining)}개 → 재제출 시도...")
        resubmitted = set()
        for link in remaining:
            a = submitted_map[link]
            ok = await submit_article(
                news_id=link,
                title=a.get("title") or a.get("headline") or "",
                link=link,
                article_text=(a.get("content") or "").strip() or None,
                summary_text=(a.get("summary") or "").strip() or None,
                tickers=a.get("tickers") or None,
            )
            if ok:
                resubmitted.add(link)
                logger.info(f"[GenAI] 재제출 성공: {link[:60]}")
            else:
                logger.warning(f"[GenAI] 재제출 실패: {link[:60]}")

        remaining2 = resubmitted.copy()
        for i in range(min(len(resubmitted) * 3 + 10, 100)):
            if not remaining2:
                break
            try:
                resp = await get_client().post("/api/v1/jobs/process-next")
                data = resp.json()
                if not data.get("processed", False):
                    logger.info(f"[GenAI] 재처리 큐 소진 (총 {i}개 처리)")
                    break
                p_id = (data.get("news_id") or "").rstrip("/")
                p_outcome = data.get("analysis_outcome")
                enrichment = data.get("enrichment")
                if p_id in remaining2:
                    remaining2.discard(p_id)
                    if enrichment and p_outcome in ("success", "partial_success"):
                        results[p_id] = _parse_storage_payload(enrichment)
                        logger.info(f"[GenAI] 재처리 결과 수집: {p_id[:60]} outcome={p_outcome}")
                    else:
                        results[p_id] = _unavailable(f"재처리 실패: {p_outcome}")
                        logger.warning(f"[GenAI] 재처리 실패: {p_id[:60]} outcome={p_outcome}")
            except Exception as e:
                logger.error(f"[GenAI] 재처리 오류: {e}")
                break

    output = []
    for a in valid:
        link = (a.get("link") or a.get("source_url") or "").rstrip("/")
        result = results.get(link) or _unavailable("결과 없음")
        output.append({**a, "enrichment": result})

    return output
