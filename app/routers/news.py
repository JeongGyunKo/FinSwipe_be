from fastapi import APIRouter
from pydantic import BaseModel
from app.core.supabase import supabase_admin as supabase
from app.services.news_collector import collect_market_news, analyze_and_update, reanalyze_unanalyzed
from app.services.analyzer import analyze_news_batch, check_genai_health, submit_article, _unavailable

router = APIRouter()


class AnalyzeRequest(BaseModel):
    news_id: str
    headline: str
    source_url: str
    content: str = ""
    tickers: list[str] = []
    published_at: str = ""


@router.get("/test")
async def test_supabase():
    result = supabase.table("news_articles").select("*").limit(5).execute()
    return {
        "status": "ok",
        "count": len(result.data),
        "data": result.data
    }


@router.post("/collect")
async def collect_news():
    """뉴스 수집 트리거 (수동)"""
    result = await collect_market_news()
    return result


@router.get("/latest")
async def get_latest_news(limit: int = 20):
    """최신 뉴스 조회"""
    result = supabase.table("news_articles")\
        .select("*")\
        .order("published_at", desc=True)\
        .limit(limit)\
        .execute()
    return {
        "count": len(result.data),
        "data": result.data
    }


@router.get("/genai/health")
async def genai_health():
    """GenAI 서버 상태 확인"""
    return await check_genai_health()


@router.post("/analyze")
async def analyze_single(body: AnalyzeRequest):
    """단일 뉴스 분석 (GenAI 서버 - 요약 + 감성)"""
    enriched = await analyze_news_batch([{
        "link": body.source_url,
        "title": body.headline,
        "content": body.content or "",
        "tickers": body.tickers or [],
    }])
    return enriched[0].get("enrichment") if enriched else _unavailable("분석 실패")


@router.post("/translate-all")
async def translate_all_articles():
    """번역 안 된 기사 전체 번역 (백그라운드)"""
    import asyncio
    from app.services.translator import translate_article

    result = supabase.table("news_articles")\
        .select("id, headline, summary_3lines, source_url")\
        .is_("headline_ko", "null")\
        .not_.is_("summary_3lines", "null")\
        .execute()
    articles = result.data
    if not articles:
        return {"triggered": 0, "message": "번역할 기사 없음"}

    async def _translate_all():
        success = 0
        failed = 0
        for article in articles:
            try:
                headline = article.get("headline") or ""
                summary_3lines = article.get("summary_3lines") or []
                if not headline and not summary_3lines:
                    continue
                headline_ko, summary_3lines_ko = await translate_article(headline, summary_3lines)
                supabase.table("news_articles").update({
                    "headline_ko": headline_ko,
                    "summary_3lines_ko": summary_3lines_ko,
                }).eq("id", article["id"]).execute()
                success += 1
            except Exception as e:
                failed += 1
                print(f"[번역] 실패 ({article.get('source_url', '')[:50]}): {e}")
        print(f"[번역] 완료 → 성공 {success}개 / 실패 {failed}개")

    asyncio.create_task(_translate_all())
    return {"triggered": len(articles), "message": f"{len(articles)}개 번역 시작 (백그라운드)"}


@router.get("/reanalyze")
async def reanalyze_endpoint(limit: int = 50):
    """sentiment가 NULL인 기사 재분석 트리거 (백그라운드)"""
    import asyncio
    asyncio.create_task(reanalyze_unanalyzed(limit))
    return {"triggered": True}


@router.get("/analyze/latest")
async def analyze_latest(limit: int = 10):
    """최신 뉴스 일괄 병렬 분석 (GenAI)"""
    result = supabase.table("news_articles")\
        .select("*")\
        .order("published_at", desc=True)\
        .limit(limit)\
        .execute()
    analyzed = await analyze_news_batch(result.data)
    return {
        "count": len(analyzed),
        "data": analyzed
    }


class DiagnoseRequest(BaseModel):
    source_url: str


@router.post("/diagnose")
async def diagnose_article(body: DiagnoseRequest):
    """특정 기사를 GenAI에 직접 제출 → process-next 원본 응답 전체 반환 (실패 원인 진단용)"""
    import asyncio
    from app.services.analyzer import get_client, submit_article

    url = body.source_url.rstrip("/")

    # DB에서 기사 조회
    res = supabase.table("news_articles").select("*").eq("source_url", url).limit(1).execute()
    if not res.data:
        res = supabase.table("news_articles").select("*").eq("source_url", url + "/").limit(1).execute()
    if not res.data:
        return {"error": f"DB에서 기사를 찾을 수 없음: {url}"}

    article = res.data[0]
    title = article.get("headline") or article.get("title") or ""
    content = (article.get("content") or "").strip()
    summary = (article.get("summary") or "").strip()

    # GenAI 제출
    ok = await submit_article(
        news_id=url,
        title=title,
        link=url,
        article_text=content or None,
        summary_text=summary or None,
    )
    if not ok:
        return {"error": "GenAI 제출 실패 (HTTP 오류)"}

    # process-next 로 결과 수집 (최대 30회 시도)
    client = get_client()
    for i in range(30):
        resp = await client.post("/api/v1/jobs/process-next")
        data = resp.json()
        if not data.get("processed", False):
            return {
                "submitted": True,
                "result": "큐 소진 — 기사가 처리되지 않음",
                "attempts": i,
                "article_info": {
                    "url": url,
                    "title": title,
                    "content_length": len(content),
                    "has_summary": bool(summary),
                },
            }
        p_id = (data.get("news_id") or "").rstrip("/")
        if p_id == url:
            # 원본 응답 전체 반환
            return {
                "submitted": True,
                "attempts": i + 1,
                "raw_response": data,
                "article_info": {
                    "url": url,
                    "title": title,
                    "content_length": len(content),
                    "has_summary": bool(summary),
                },
            }
        # 다른 기사가 먼저 나온 경우 계속 대기
        await asyncio.sleep(0.1)

    return {"error": "30회 시도 후 결과 없음", "submitted": True}
