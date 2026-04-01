import asyncio
import httpx
from app.core.config import settings

# GenAI 서버 동시 요청 제한 (1로 고정)
_semaphore = asyncio.Semaphore(1)

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


async def enrich_article(
    news_id: str,
    title: str,
    link: str,
    article_text: str | None = None,
    summary_text: str | None = None,
    tickers: list[str] | None = None,
) -> dict:
    """
    GenAI 서버로 기사 분석 요청 (비동기 큐 방식).
    1) /api/v1/articles/enrich-text 로 제출 → 202
    2) /api/v1/jobs/process-next 로 워커 트리거
    3) /api/v1/news/{news_id}/result 폴링 → 완료 시 결과 반환
    """
    async with _semaphore:
        try:
            payload: dict = {
                "news_id": news_id,
                "title": title,
                "link": link,
            }
            if article_text:
                payload["article_text"] = article_text
            if summary_text:
                payload["summary_text"] = summary_text
            if tickers:
                payload["ticker"] = tickers

            # Step 1: 제출
            submit_resp = await get_client().post("/api/v1/articles/enrich-text", json=payload)
            submit_resp.raise_for_status()

            # Step 2: 워커 트리거
            await get_client().post("/api/v1/jobs/process-next")

            # Step 3: 결과 폴링 (최대 20회 × 3초 = 60초)
            # 404 = 아직 처리 안 됨 → process-next 재호출로 큐 드레인
            for attempt in range(20):
                await asyncio.sleep(3)
                result_resp = await get_client().get(f"/api/v1/news/{news_id}/result")

                if result_resp.status_code == 404:
                    # 아직 처리 안 됨 → 워커 재트리거
                    await get_client().post("/api/v1/jobs/process-next")
                    continue

                result_resp.raise_for_status()
                data = result_resp.json()
                state = data.get("processing_state")

                if state == "completed":
                    return _parse_result(data.get("result") or {})
                elif state == "failed":
                    err = data.get("error_code") or "unknown"
                    print(f"[GenAI] 처리 실패: {news_id[:50]} | {err}")
                    return _unavailable(f"GenAI 처리 실패: {err}")
                elif state in ("queued", "retry_pending"):
                    # 큐에 있으나 처리 안 됨 → 워커 재트리거
                    await get_client().post("/api/v1/jobs/process-next")

            print(f"[GenAI] 폴링 타임아웃: {news_id[:50]}")
            return _unavailable("GenAI 폴링 타임아웃 (60초)")

        except httpx.ConnectError as e:
            print(f"[GenAI 오류] 연결 실패: {e}")
            return _unavailable("GenAI 서버 연결 불가")
        except httpx.TimeoutException:
            print(f"[GenAI 오류] 타임아웃")
            return _unavailable("GenAI 서버 응답 시간 초과")
        except httpx.HTTPStatusError as e:
            print(f"[GenAI 오류] HTTP {e.response.status_code} | {e.response.text[:200]}")
            if e.response.status_code == 503:
                return _unavailable("GenAI 서버 일시 중단")
            return _unavailable(f"GenAI 오류: HTTP {e.response.status_code}")
        except RuntimeError as e:
            print(f"[GenAI 오류] 런타임: {e}")
            return _unavailable(str(e))
        except Exception as e:
            print(f"[GenAI 오류] {type(e).__name__}: {e}")
            return _unavailable(str(e))


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
    """뉴스 목록 순차 분석 (semaphore=1)"""
    valid = [
        a for a in articles
        if (a.get("link") or a.get("source_url") or "").startswith("http")
    ]

    tasks = [
        enrich_article(
            news_id=str(a.get("link") or a.get("source_url") or a.get("id") or ""),
            title=a.get("title") or a.get("headline") or "",
            link=a.get("link") or a.get("source_url") or "",
            article_text=(a.get("content") or "").strip() or None,
            summary_text=(a.get("summary") or "").strip() or None,
            tickers=a.get("tickers") or None,
        )
        for a in valid
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = []
    for article, result in zip(valid, results):
        if isinstance(result, Exception):
            print(f"[GenAI 오류] 개별 분석 실패: {result}")
            result = _unavailable(str(result))
        output.append({**article, "enrichment": result})
    return output
