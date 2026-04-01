import asyncio
import httpx
from urllib.parse import quote
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


async def drain_queue(max_jobs: int = 600) -> int:
    """
    GenAI 큐를 비울 때까지 process-next 반복 호출.
    processed=False 반환 시 큐 비워짐.
    """
    count = 0
    for _ in range(max_jobs):
        try:
            resp = await get_client().post("/api/v1/jobs/process-next")
            data = resp.json()
            if not data.get("processed", False):
                break
            count += 1
            await asyncio.sleep(2)  # 기사당 평균 처리 시간 대기
        except Exception as e:
            print(f"[GenAI] process-next 오류: {e}")
            break
    return count


async def fetch_result(news_id: str) -> dict | None:
    """
    분석 결과 조회. completed 상태면 파싱된 결과 반환. 없거나 미완료면 None.
    """
    try:
        encoded_id = quote(news_id, safe="")
        resp = await get_client().get(f"/api/v1/news/{encoded_id}/result")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("processing_state") != "completed":
            return None
        return _parse_result(data.get("result") or {})
    except Exception as e:
        print(f"[GenAI] 결과 조회 실패: {news_id[:60]} | {e}")
        return None


def _parse_result(result: dict) -> dict:
    """ArticleEnrichmentResponse → 우리 포맷으로 변환"""
    sentiment = result.get("sentiment")
    sentiment_block = None
    if isinstance(sentiment, dict):
        sentiment_block = {
            "label": sentiment.get("label"),
            "score": sentiment.get("score"),
            "confidence": sentiment.get("confidence"),
        }

    summary_3lines = [
        s.get("text") for s in result.get("summary_3lines", [])
        if isinstance(s, dict) and s.get("text")
    ]

    mixed = result.get("mixed_flags")

    return {
        "status": result.get("status"),
        "outcome": result.get("outcome"),
        "sentiment": sentiment_block,
        "summary_3lines": summary_3lines,
        "is_mixed": mixed.get("is_mixed") if isinstance(mixed, dict) else None,
        "error": result.get("error"),
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
    """단일 엔드포인트용 분석 (소량 기사)"""
    valid = [
        a for a in articles
        if (a.get("link") or a.get("source_url") or "").startswith("http")
    ]

    submitted = []
    for a in valid:
        link = a.get("link") or a.get("source_url") or ""
        ok = await submit_article(
            news_id=link,
            title=a.get("title") or a.get("headline") or "",
            link=link,
            article_text=(a.get("content") or "").strip() or None,
            summary_text=(a.get("summary") or "").strip() or None,
            tickers=a.get("tickers") or None,
        )
        submitted.append(ok)

    await drain_queue(max_jobs=len(valid) + 20)

    output = []
    for article, ok in zip(valid, submitted):
        if not ok:
            output.append({**article, "enrichment": _unavailable("제출 실패")})
            continue
        link = article.get("link") or article.get("source_url") or ""
        result = await fetch_result(link) or _unavailable("결과 없음")
        output.append({**article, "enrichment": result})
    return output
