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
        body = resp.json() if resp.status_code in (200, 202) else {}
        queued = body.get("queued")
        state = body.get("processing_state")
        print(f"[GenAI] submit {news_id[:60]} → status={resp.status_code} queued={queued} state={state}")
        return resp.status_code in (200, 202)
    except Exception as e:
        print(f"[GenAI] 제출 실패: {news_id[:60]} | {e}")
        return False


async def drain_queue(target_ids: set[str] | None = None, max_jobs: int = 10000) -> int:
    """
    GenAI 큐 처리. target_ids가 주어지면 해당 기사가 모두 완료되면 조기 종료.
    processed=False 반환 시 큐 비워짐.
    """
    count = 0
    remaining = set(target_ids) if target_ids else None
    for _ in range(max_jobs):
        try:
            resp = await get_client().post("/api/v1/jobs/process-next")
            data = resp.json()
            if not data.get("processed", False):
                break
            count += 1
            p_state = data.get("processing_state")
            p_outcome = data.get("analysis_outcome")
            p_id = data.get("news_id", "")
            print(f"[GenAI] process-next #{count}: news_id={p_id[:60]} state={p_state} outcome={p_outcome}")
            # 우리가 제출한 기사가 처리됐으면 remaining에서 제거
            if remaining is not None:
                if p_id:
                    remaining.discard(p_id)
                if not remaining:
                    print(f"[GenAI] 목표 기사 전부 처리 완료, drain 종료 (총 {count}개)")
                    break
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
        # httpx base_url 병합 시 %3A 등이 디코딩될 수 있으므로 절대 URL 직접 구성
        base = str(get_client().base_url).rstrip("/")
        full_url = f"{base}/api/v1/news/{encoded_id}/result"
        print(f"[DEBUG] fetch_result URL: {full_url}")
        resp = await get_client().get(full_url)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        print(f"[DEBUG] fetch_result status={resp.status_code} state={body.get('processing_state')} outcome={body.get('result', {}).get('outcome') if body.get('result') else None}")
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
    submitted_ids: set[str] = set()
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
        if ok:
            submitted_ids.add(link)

    print(f"[GenAI] 제출 완료 {len(submitted_ids)}개, 큐 처리 시작...")
    await drain_queue(target_ids=submitted_ids)  # 우리 기사가 처리되면 즉시 종료

    output = []
    for article, ok in zip(valid, submitted):
        if not ok:
            output.append({**article, "enrichment": _unavailable("제출 실패")})
            continue
        link = article.get("link") or article.get("source_url") or ""
        result = await fetch_result(link) or _unavailable("결과 없음")
        output.append({**article, "enrichment": result})
    return output
