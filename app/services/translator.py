import httpx
from app.core.config import settings

DEEPL_URL = "https://api-free.deepl.com/v2/translate"

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"Authorization": f"DeepL-Auth-Key {settings.deepl_api_key}"},
            timeout=15.0,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def translate_texts(texts: list[str]) -> list[str]:
    """텍스트 목록을 한국어로 번역 (DeepL Free API)"""
    if not texts:
        return texts
    if not settings.deepl_api_key:
        print("[DeepL] API 키 없음 → 번역 스킵")
        return texts

    try:
        resp = await get_client().post(
            DEEPL_URL,
            json={
                "text": texts,
                "target_lang": "KO",
                "source_lang": "EN",
            },
        )
        print(f"[DeepL] 응답 status={resp.status_code}")
        if resp.status_code != 200:
            print(f"[DeepL] 에러 응답: {resp.text[:200]}")
            return texts
        translations = resp.json().get("translations", [])
        print(f"[DeepL] 번역 완료 {len(translations)}개")
        return [t.get("text", original) for t, original in zip(translations, texts)]
    except Exception as e:
        print(f"[DeepL] 번역 실패: {e}")
        return texts


async def translate_article(headline: str, summary_3lines: list[str]) -> tuple[str, list[str]]:
    """기사 제목 + 3줄 요약 번역"""
    texts = [headline] + summary_3lines
    translated = await translate_texts(texts)
    return translated[0], translated[1:]
