import asyncio
import httpx
from app.core.config import settings

# FinBERT 동시 요청 제한 (Render 무료 서버 부하 방지)
_semaphore = asyncio.Semaphore(3)


async def analyze_sentiment(text: str) -> dict:
    """FinBERT API로 단일 텍스트 감성 분석"""
    async with _semaphore:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.finbert_url}/predict",
                    json={"text": text},
                    auth=(settings.finbert_user, settings.finbert_password)
                )
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
        "error": result.get("error"),  # 서버 꺼진 경우 사유 포함
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
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                settings.finbert_url,
                auth=(settings.finbert_user, settings.finbert_password)
            )
            if response.status_code == 200:
                return {"status": "ok"}
            return {"status": "error", "code": response.status_code}
    except httpx.ConnectError:
        return {"status": "offline", "reason": "연결 불가 (서버 꺼짐)"}
    except httpx.TimeoutException:
        return {"status": "offline", "reason": "응답 시간 초과"}
    except Exception as e:
        return {"status": "offline", "reason": str(e)}
