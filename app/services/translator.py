import httpx
from app.core.config import settings

DEEPL_URL = "https://api-free.deepl.com/v2/translate"


async def translate_texts(texts: list[str]) -> list[str]:
    """텍스트 목록을 한국어로 번역 (DeepL Free API)"""
    if not texts or not settings.deepl_api_key:
        return texts

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DEEPL_URL,
                headers={"Authorization": f"DeepL-Auth-Key {settings.deepl_api_key}"},
                json={
                    "text": texts,
                    "target_lang": "KO",
                    "source_lang": "EN",
                },
            )
            resp.raise_for_status()
            translations = resp.json().get("translations", [])
            return [t.get("text", original) for t, original in zip(translations, texts)]
    except Exception as e:
        print(f"[DeepL] 번역 실패: {e}")
        return texts


async def translate_article(headline: str, summary_3lines: list[str]) -> tuple[str, list[str]]:
    """기사 제목 + 3줄 요약 번역"""
    texts = [headline] + summary_3lines
    translated = await translate_texts(texts)
    return translated[0], translated[1:]
