import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.core.jobs import create_job, get_job
from app.core.limiter import limiter
from app.core.supabase import supabase_admin as supabase
from app.services.news_collector import collect_market_news, reanalyze_unanalyzed
from app.services.analyzer import analyze_news_batch, check_genai_health, submit_article, get_client, _unavailable

logger = logging.getLogger(__name__)
router = APIRouter()

_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def _require_admin(key: str | None = Depends(_api_key_header)) -> None:
    if not key or key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


class AnalyzeRequest(BaseModel):
    headline: str = Field(..., min_length=1, max_length=500)
    source_url: str = Field(..., pattern=r"^https?://")
    content: str = Field("", max_length=50000)
    tickers: list[str] = Field(default_factory=list, max_length=20)


class DiagnoseRequest(BaseModel):
    source_url: str = Field(..., pattern=r"^https?://")


# ── 관리용 엔드포인트 ────────────────────────────────────────────

@router.get("/test", dependencies=[Depends(_require_admin)])
@limiter.limit("30/minute")
async def test_supabase(request: Request):
    result = await asyncio.to_thread(
        lambda: supabase.table("news_articles").select("*").limit(5).execute()
    )
    return {"status": "ok", "count": len(result.data), "data": result.data}


@router.post("/collect", dependencies=[Depends(_require_admin)])
@limiter.limit("5/minute")
async def collect_news(request: Request):
    """뉴스 수집 트리거 (수동)"""
    return await collect_market_news()


@router.post("/reanalyze", dependencies=[Depends(_require_admin)])
@limiter.limit("5/minute")
async def reanalyze_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """sentiment가 NULL인 기사 재분석 트리거 (백그라운드) — job_id로 상태 조회 가능"""
    job_id = create_job("reanalyze")
    asyncio.create_task(reanalyze_unanalyzed(limit, job_id=job_id))
    return {"job_id": job_id, "status": "pending"}


@router.post("/translate-all", dependencies=[Depends(_require_admin)])
@limiter.limit("2/minute")
async def translate_all_articles(request: Request):
    """번역 안 된 기사 전체 번역 (백그라운드) — job_id로 상태 조회 가능"""
    from app.core.jobs import start_job, finish_job, fail_job
    from app.services.translator import translate_article, translate_xai_highlights

    result = await asyncio.to_thread(
        lambda: supabase.table("news_articles")
            .select("id, headline, summary_3lines, xai, source_url")
            .is_("headline_ko", "null")
            .not_.is_("summary_3lines", "null")
            .execute()
    )
    articles = result.data
    if not articles:
        return {"triggered": 0, "message": "번역할 기사 없음"}

    job_id = create_job("translate-all")

    def _db_update_translation(article_id: str, headline_ko: str, summary_3lines_ko: list, xai_ko: list | None) -> None:
        supabase.table("news_articles").update({
            "headline_ko": headline_ko,
            "summary_3lines_ko": summary_3lines_ko,
            "xai_ko": xai_ko,
        }).eq("id", article_id).execute()

    async def _translate_all():
        start_job(job_id)
        success = 0
        failed = 0
        for article in articles:
            try:
                headline = article.get("headline") or ""
                summary_3lines = article.get("summary_3lines") or []
                if not headline and not summary_3lines:
                    continue
                headline_ko, summary_3lines_ko = await translate_article(headline, summary_3lines)
                xai_ko = await translate_xai_highlights(article.get("xai"))
                await asyncio.to_thread(_db_update_translation, article["id"], headline_ko, summary_3lines_ko, xai_ko)
                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"[번역] 실패 ({article.get('source_url', '')[:50]}): {e}")
        logger.info(f"[번역] 완료 → 성공 {success}개 / 실패 {failed}개")
        finish_job(job_id, {"success": success, "failed": failed})

    asyncio.create_task(_translate_all())
    return {"job_id": job_id, "status": "pending", "total": len(articles)}


@router.post("/backfill-xai-ko", dependencies=[Depends(_require_admin)])
@limiter.limit("2/minute")
async def backfill_xai_ko(request: Request):
    """xai는 있지만 xai_ko가 없는 기사 일괄 번역 (백그라운드)"""
    from app.core.jobs import start_job, finish_job
    from app.services.translator import translate_xai_highlights

    result = await asyncio.to_thread(
        lambda: supabase.table("news_articles")
            .select("id, xai, source_url")
            .is_("xai_ko", "null")
            .not_.is_("xai", "null")
            .execute()
    )
    articles = result.data
    if not articles:
        return {"triggered": 0, "message": "채울 기사 없음"}

    job_id = create_job("backfill-xai-ko")

    async def _backfill():
        start_job(job_id)
        success = 0
        failed = 0
        for article in articles:
            try:
                xai_ko = await translate_xai_highlights(article.get("xai"))
                await asyncio.to_thread(
                    lambda: supabase.table("news_articles")
                        .update({"xai_ko": xai_ko})
                        .eq("id", article["id"])
                        .execute()
                )
                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"[xai_ko backfill] 실패 ({article.get('source_url', '')[:50]}): {e}")
        logger.info(f"[xai_ko backfill] 완료 → 성공 {success}개 / 실패 {failed}개")
        finish_job(job_id, {"success": success, "failed": failed})

    asyncio.create_task(_backfill())
    return {"job_id": job_id, "status": "pending", "total": len(articles)}


@router.get("/jobs/{job_id}", dependencies=[Depends(_require_admin)])
async def get_job_status(job_id: str):
    """백그라운드 작업 상태 조회"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/analyze", dependencies=[Depends(_require_admin)])
@limiter.limit("10/minute")
async def analyze_single(request: Request, body: AnalyzeRequest):
    """단일 뉴스 분석 (GenAI 서버 - 요약 + 감성)"""
    enriched = await analyze_news_batch([{
        "link": body.source_url,
        "title": body.headline,
        "content": body.content or "",
        "tickers": body.tickers or [],
    }])
    return enriched[0].get("enrichment") if enriched else _unavailable("분석 실패")


@router.get("/analyze/latest", dependencies=[Depends(_require_admin)])
@limiter.limit("5/minute")
async def analyze_latest(request: Request, limit: int = Query(default=10, ge=1, le=50)):
    """최신 뉴스 일괄 분석 (GenAI)"""
    result = await asyncio.to_thread(
        lambda: supabase.table("news_articles")
            .select("*")
            .order("published_at", desc=True)
            .limit(limit)
            .execute()
    )
    analyzed = await analyze_news_batch(result.data)
    return {"count": len(analyzed), "data": analyzed}


@router.post("/diagnose", dependencies=[Depends(_require_admin)])
@limiter.limit("10/minute")
async def diagnose_article(request: Request, body: DiagnoseRequest):
    """특정 기사를 GenAI에 직접 제출 → process-next 원본 응답 전체 반환 (실패 원인 진단용)"""
    url = body.source_url.rstrip("/")

    def _fetch_article():
        res = supabase.table("news_articles").select("*").eq("source_url", url).limit(1).execute()
        if not res.data:
            res2 = supabase.table("news_articles").select("*").eq("source_url", url + "/").limit(1).execute()
            return res2.data
        return res.data

    data = await asyncio.to_thread(_fetch_article)
    if not data:
        raise HTTPException(status_code=404, detail=f"DB에서 기사를 찾을 수 없음: {url}")

    article = data[0]
    title = article.get("headline") or ""
    content = (article.get("content") or "").strip()
    summary = (article.get("summary") or "").strip()

    ok = await submit_article(
        news_id=url, title=title, link=url,
        article_text=content or None,
        summary_text=summary or None,
    )
    if not ok:
        raise HTTPException(status_code=502, detail="GenAI 제출 실패 (HTTP 오류)")

    client = get_client()
    for i in range(30):
        resp = await client.post("/api/v1/jobs/process-next")
        data = resp.json()
        if not data.get("processed", False):
            raise HTTPException(status_code=504, detail=f"큐 소진 — 기사가 처리되지 않음 (시도 {i}회)")
        p_id = (data.get("news_id") or "").rstrip("/")
        if p_id == url:
            return {
                "submitted": True,
                "attempts": i + 1,
                "raw_response": data,
                "article_info": {"url": url, "title": title, "content_length": len(content)},
            }
        await asyncio.sleep(0.1)

    raise HTTPException(status_code=504, detail="30회 시도 후 결과 없음")


# ── 공개 엔드포인트 ────────────────────────────────────────────

@router.get("/latest")
@limiter.limit("30/minute")
async def get_latest_news(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """최신 뉴스 조회 (캐시 30초)"""
    cache_key = f"latest:{limit}:{offset}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    result = await asyncio.to_thread(
        lambda: supabase.table("news_articles")
            .select("*")
            .order("published_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
    )
    response = {"count": len(result.data), "offset": offset, "data": result.data}
    cache_set(cache_key, response, ttl_seconds=30)
    return response


@router.get("/genai/health")
@limiter.limit("10/minute")
async def genai_health(request: Request):
    """GenAI 서버 상태 확인"""
    return await check_genai_health()
