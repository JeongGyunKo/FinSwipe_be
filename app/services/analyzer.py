import asyncio
import httpx
from app.core.config import settings

# GenAI 서버 동시 요청 제한 (sentiment 모델 동시 접근 불가 → 1로 고정)
_semaphore = asyncio.Semaphore(1)

# 앱 전체에서 재사용할 클라이언트 (연결 풀)
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("GenAI 클라이언트가 초기화되지 않았습니다")
    return _client


async def init_client() -> None:
    """앱 시작 시 한 번 호출"""
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.genai_url,
        auth=(settings.genai_user, settings.genai_password),
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


async def close_client() -> None:
    """앱 종료 시 한 번 호출"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def check_genai_health() -> dict:
    """GenAI 서버 상태 확인"""
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
    except RuntimeError as e:
        return {"status": "offline", "reason": str(e)}
    except Exception as e:
        return {"status": "offline", "reason": str(e)}


async def enrich_article(
    news_id: str,
    title: str,
    link: str,
    content: str | None = None,
    tickers: list[str] | None = None,
    published_at: str | None = None,
) -> dict:
    """
    GenAI 서버로 기사 분석 요청.
    content(본문 텍스트)가 있으면 직접 전달 → 크롤링 없이 분석.
    서버 꺼짐 / 오류 시 unavailable 반환.
    """
    async with _semaphore:
        try:
            payload: dict = {
                "news_id": news_id,
                "title": title,
                "link": link,
            }
            if content:
                payload["text"] = content
            if tickers:
                payload["ticker"] = tickers
            if published_at:
                payload["published_at"] = published_at

            response = await get_client().post("/api/v1/articles/enrich", json=payload)
            response.raise_for_status()
            data = response.json()

            sentiment = data.get("sentiment")
            mixed = data.get("mixed_flags")

            # sentiment가 None이면 전체 블록을 None으로 처리
            sentiment_block = None
            if isinstance(sentiment, dict):
                sentiment_block = {
                    "label": sentiment.get("label"),
                    "score": sentiment.get("score"),
                    "confidence": sentiment.get("confidence"),
                }

            # summary_3lines에서 text 또는 content 키로 추출
            summary_3lines = [
                s.get("text") or s.get("content", "") for s in data.get("summary_3lines", [])
                if isinstance(s, dict) and (s.get("text") or s.get("content"))
            ]

            return {
                "status": data.get("status"),
                "outcome": data.get("outcome"),
                "sentiment": sentiment_block,
                "summary_3lines": summary_3lines,
                "is_mixed": mixed.get("is_mixed") if isinstance(mixed, dict) else None,
                "error": data.get("error"),
            }

        except httpx.ConnectError as e:
            print(f"[GenAI 오류] 연결 실패: {e}")
            return _unavailable("GenAI 서버에 연결할 수 없습니다 (서버 꺼짐)")
        except httpx.TimeoutException as e:
            print(f"[GenAI 오류] 타임아웃: {e}")
            return _unavailable("GenAI 서버 응답 시간 초과")
        except httpx.HTTPStatusError as e:
            print(f"[GenAI 오류] HTTP {e.response.status_code}")
            if e.response.status_code == 503:
                return _unavailable("GenAI 서버 일시 중단")
            return _unavailable(f"GenAI 서버 오류: HTTP {e.response.status_code}")
        except RuntimeError as e:
            print(f"[GenAI 오류] 런타임: {e}")
            return _unavailable(str(e))
        except Exception as e:
            print(f"[GenAI 오류] {type(e).__name__}: {e}")
            return _unavailable(f"알 수 없는 오류: {str(e)}")


def _build_text(article: dict) -> str | None:
    """본문 → summary → title+summary 순으로 텍스트 구성"""
    content = article.get("content")
    if content and len(content.strip()) > 100:
        return content

    title = article.get("title", article.get("headline", ""))
    summary = article.get("summary", "")
    combined = f"{title}. {summary}".strip() if summary else title
    return combined if combined else None


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
    """뉴스 목록 병렬 분석 (서버 꺼져 있어도 결과 반환)"""
    valid = [
        a for a in articles
        if (a.get("link") or a.get("source_url") or "").startswith("http")
    ]

    tasks = [
        enrich_article(
            news_id=str(a.get("id") or a.get("link") or ""),
            title=a.get("title") or a.get("headline") or "",
            link=a.get("link") or a.get("source_url") or "",
            content=_build_text(a),
            tickers=a.get("tickers") or None,
            published_at=a.get("publishDate") or a.get("published_at"),
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
