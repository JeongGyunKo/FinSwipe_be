import asyncio
import httpx
from app.core.config import settings

# FinBERT 동시 요청 제한 (Render 무료 서버 부하 방지)
_semaphore = asyncio.Semaphore(3)

# 앱 생애주기 동안 재사용할 클라이언트 (연결 풀)
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("FinBERT 클라이언트가 초기화되지 않았습니다. init_client()를 먼저 호출하세요.")
    return _client


async def init_client() -> None:
    """앱 시작 시 한 번 호출 — 클라이언트 생성 및 연결 풀 초기화"""
    global _client
    _client = httpx.AsyncClient(
        base_url=settings.finbert_url,
        auth=(settings.finbert_user, settings.finbert_password),
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


async def close_client() -> None:
    """앱 종료 시 한 번 호출 — 클라이언트 정리"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def analyze_sentiment(text: str) -> dict:
    """FinBERT API로 단일 텍스트 감성 분석"""
    async with _semaphore:
        try:
            response = await get_client().post("/predict", json={"text": text})
            response.raise_for_status()
            return response.json()

        except httpx.ConnectError:
            return _unavailable("FinBERT 서버에 연결할 수 없습니다 (서버 꺼짐)")
        except httpx.TimeoutException:
            return _unavailable("FinBERT 서버 응답 시간 초과")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                return _unavailable("FinBERT 서버가 일시 중단 상태입니다 (Render suspended)")
            return _unavailable(f"FinBERT 오류: HTTP {e.response.status_code}")
        except RuntimeError as e:
            return _unavailable(str(e))
        except Exception as e:
            return _unavailable(f"알 수 없는 오류: {str(e)}")


def _unavailable(reason: str) -> dict:
    return {
        "label": "unavailable",
        "positive": None,
        "negative": None,
        "neutral": None,
        "error": reason,
    }


async def analyze_news_sentiment(headline: str, summary: str = "") -> dict:
    """뉴스 헤드라인 + 요약으로 감성 분석"""
    text = f"{headline}. {summary}".strip() if summary else headline
    result = await analyze_sentiment(text)
    return {
        "label": result.get("label"),
        "positive": result.get("positive"),
        "negative": result.get("negative"),
        "neutral": result.get("neutral"),
        "error": result.get("error"),
    }


async def analyze_news_batch(articles: list[dict]) -> list[dict]:
    """뉴스 목록 병렬 감성 분석 (FinBERT 꺼져 있어도 결과 반환)"""
    tasks = [
        analyze_news_sentiment(
            headline=a.get("headline", ""),
            summary=a.get("summary", ""),
        )
        for a in articles
    ]
    results = await asyncio.gather(*tasks)
    return [
        {**article, "sentiment": result}
        for article, result in zip(articles, results)
    ]


async def check_finbert_health() -> dict:
    """FinBERT 서버 상태 확인"""
    try:
        response = await get_client().get("/health")
        if response.status_code == 200:
            return {"status": "ok"}
        if response.status_code == 503:
            return {"status": "suspended", "reason": "Render 서버 일시 중단"}
        return {"status": "error", "code": response.status_code}

    except httpx.ConnectError:
        return {"status": "offline", "reason": "연결 불가 (서버 꺼짐)"}
    except httpx.TimeoutException:
        return {"status": "offline", "reason": "응답 시간 초과"}
    except RuntimeError as e:
        return {"status": "offline", "reason": str(e)}
    except Exception as e:
        return {"status": "offline", "reason": str(e)}
