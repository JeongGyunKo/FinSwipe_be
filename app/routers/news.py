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
from app.services.ticker_names import enrich_tickers, search_tickers, TICKER_NAMES, TICKER_LIST

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

def _attach_ticker_names(articles: list[dict]) -> list[dict]:
    """각 기사의 tickers 배열에 회사명을 추가해 ticker_names 필드로 반환"""
    for article in articles:
        tickers = article.get("tickers") or []
        article["ticker_names"] = enrich_tickers(tickers)
    return articles


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
    articles = _attach_ticker_names(result.data)
    response = {"count": len(articles), "offset": offset, "data": articles}
    cache_set(cache_key, response, ttl_seconds=30)
    return response


@router.get("/search")
@limiter.limit("30/minute")
async def search_news(
    request: Request,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    한국어/영문 회사명 또는 티커로 뉴스 검색.
    예: ?q=애플  ?q=AAPL  ?q=nvidia
    """
    cache_key = f"search:{q}:{limit}:{offset}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # 1) 입력값이 티커 자체인지 먼저 확인 (AAPL 등)
    q_upper = q.strip().upper()
    if q_upper in TICKER_NAMES:
        matched_tickers = [q_upper]
    else:
        # 2) 한국어/영문 회사명으로 티커 검색
        matched_tickers = search_tickers(q)

    if not matched_tickers:
        response = {"count": 0, "offset": offset, "query": q, "matched_tickers": [], "data": []}
        cache_set(cache_key, response, ttl_seconds=30)
        return response

    # 3) 매칭된 티커 중 하나라도 포함된 기사 조회
    # Supabase array overlap: tickers && ARRAY['AAPL','APPL']
    ticker_filter = "{" + ",".join(matched_tickers) + "}"

    result = await asyncio.to_thread(
        lambda: supabase.table("news_articles")
            .select("*")
            .overlaps("tickers", ticker_filter)
            .order("published_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
    )
    articles = _attach_ticker_names(result.data)
    response = {
        "count": len(articles),
        "offset": offset,
        "query": q,
        "matched_tickers": matched_tickers,
        "data": articles,
    }
    cache_set(cache_key, response, ttl_seconds=30)
    return response


@router.get("/tickers")
@limiter.limit("30/minute")
async def get_ticker_list(request: Request):
    """지원하는 전체 티커 목록 반환 (FE 검색 자동완성용)"""
    cached = cache_get("ticker_list")
    if cached is not None:
        return cached
    response = {"count": len(TICKER_LIST), "data": TICKER_LIST}
    cache_set("ticker_list", response, ttl_seconds=3600)  # 1시간 캐시 (데이터 불변)
    return response


@router.get("/genai/health")
@limiter.limit("10/minute")
async def genai_health(request: Request):
    """GenAI 서버 상태 확인"""
    return await check_genai_health()
