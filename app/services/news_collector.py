import asyncio
import logging
import httpx
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse
from app.core.config import settings
from app.core.jobs import start_job, finish_job, fail_job
from app.core.supabase import supabase_admin
from app.services.analyzer import analyze_news_batch
from app.services.ticker_names import TICKER_NAMES

logger = logging.getLogger(__name__)
_analysis_lock = asyncio.Lock()

FINLIGHT_BASE_URL = "https://api.finlight.me"

# 암호화폐 티커 블록리스트
CRYPTO_TICKERS = {
    "BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "SHIB", "MATIC",
    "LTC", "TRX", "AVAX", "LINK", "UNI", "ATOM", "XLM", "ETC", "BCH", "ALGO",
    "VET", "ICP", "FIL", "THETA", "XMR", "EOS", "AAVE", "GRT", "MKR", "COMP",
    "SNX", "YFI", "SUSHI", "CRV", "BAT", "ZEC", "DASH", "NEO", "WAVES", "IOTA",
    "XTZ", "EGLD", "HBAR", "NEAR", "FTM", "ONE", "SAND", "MANA", "AXS", "ENJ",
    "CHZ", "FLOW", "GALA", "IMX", "APE", "LRC", "CRO", "KCS", "HT", "OKB",
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FRAX", "LUSD", "USDD",
    "WBTC", "STETH", "RETH", "CBETH", "WETH",
    "SUI", "APT", "ARB", "OP", "BLUR", "PEPE", "FLOKI", "BONK", "WIF", "JUP",
}


def _filter_tickers(companies: list) -> list[str]:
    """아시아 증시(숫자) 티커 및 암호화폐 티커 제거 → 미국 주식 티커만 남김"""
    result = []
    for c in companies:
        ticker = (c.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        if not ticker.isalpha():
            continue
        if ticker in CRYPTO_TICKERS:
            continue
        result.append(ticker)
    return result


_finlight_client: httpx.AsyncClient | None = None


def get_finlight_client() -> httpx.AsyncClient:
    global _finlight_client
    if _finlight_client is None:
        _finlight_client = httpx.AsyncClient(
            base_url=FINLIGHT_BASE_URL,
            headers={"X-API-KEY": settings.finlight_api_key},
            timeout=30.0,
        )
    return _finlight_client


async def close_finlight_client() -> None:
    global _finlight_client
    if _finlight_client is not None:
        await _finlight_client.aclose()
        _finlight_client = None


# 7개 쿼리 × 100개 = 700개/15분, 월 최대 20,832회 (한도 41%)
COLLECTION_QUERIES = [
    "earnings beat miss EPS revenue guidance outlook forecast",
    "Apple Microsoft Google Meta Amazon Tesla NVIDIA AMD Intel Qualcomm",
    "JPMorgan Goldman Sachs Visa Mastercard PayPal Coinbase BlackRock",
    "merger acquisition IPO buyback dividend upgrade downgrade analyst",
    "Pfizer Eli Lilly Johnson UnitedHealth Exxon Chevron ConocoPhillips",
    "semiconductor AI cloud cybersecurity biotech pharma FDA approval",
    "stock rally selloff S&P500 Nasdaq Russell inflation Fed rate GDP",
]


async def _fetch_single_query(query: str, from_date: str | None = None) -> list[dict]:
    payload: dict = {
        "query": query,
        "language": "en",
        "pageSize": 100,
        "includeContent": True,
        "includeEntities": True,
        "excludeEmptyContent": True,
        "orderBy": "publishDate",
        "order": "DESC",
    }
    if from_date:
        payload["from"] = from_date

    for attempt in range(4):
        try:
            response = await get_finlight_client().post("/v2/articles", json=payload)
            if response.status_code == 429:
                wait = 15 * (attempt + 1)
                logger.warning(f"[Finlight] 429 → {wait}초 대기 후 재시도 ({attempt + 1}/4)")
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            articles = response.json().get("articles", [])
            logger.info(f"[Finlight] '{query[:40]}' → {len(articles)}개")
            return articles
        except httpx.HTTPStatusError as e:
            logger.error(f"[Finlight] HTTP {e.response.status_code}: {query[:30]}")
            return []
        except Exception as e:
            logger.error(f"[Finlight] {type(e).__name__}: {query[:30]}")
            return []
    logger.error(f"[Finlight] 4회 재시도 후 실패: {query[:30]}")
    return []


async def fetch_news_from_finlight() -> list[dict]:
    """7개 쿼리 순차 수집 → content+알려진 ticker 있는 새 기사만 반환"""
    from_date = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")

    all_articles_raw = []
    for q in COLLECTION_QUERIES:
        articles = await _fetch_single_query(q, from_date=from_date)
        all_articles_raw.extend(articles)
        await asyncio.sleep(2)  # 쿼리 간 2초 간격 (429 방지)

    def _normalize_url(url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))

    seen = set()
    all_articles = []
    for a in all_articles_raw:
        link = a.get("link")
        if link:
            normalized = _normalize_url(link)
            if normalized not in seen:
                seen.add(normalized)
                a["link"] = normalized
                all_articles.append(a)

    with_tickers = []
    for a in all_articles:
        if not a.get("summary") and not a.get("title"):
            continue
        companies = a.get("companies") or []
        known = [
            c for c in companies
            if (c.get("ticker") or "").strip().upper() in TICKER_NAMES
        ]
        if known:
            with_tickers.append(a)
    logger.info(f"[Finlight] 수집 {len(all_articles)}개 → 알려진 ticker {len(with_tickers)}개")

    links = [a["link"] for a in with_tickers]
    new_links = await asyncio.to_thread(_filter_new_links, links)
    new_articles = [a for a in with_tickers if a.get("link") in new_links]
    logger.info(f"[Finlight] 새 기사 {len(new_articles)}개")
    return new_articles


def _filter_new_links(links: list[str]) -> set[str]:
    if not links:
        return set()
    existing = set()
    chunk_size = 100
    try:
        for i in range(0, len(links), chunk_size):
            chunk = links[i:i + chunk_size]
            result = supabase_admin.table("news_articles")\
                .select("source_url")\
                .in_("source_url", chunk)\
                .execute()
            existing.update(row["source_url"] for row in result.data)
        return set(links) - existing
    except Exception as e:
        logger.error(f"기존 기사 조회 실패: {e}")
        return set(links)


def save_news_to_db(articles: list[dict]) -> dict:
    if not articles:
        return {"saved": 0, "skipped": 0}

    valid = []
    skipped = 0

    for article in articles:
        if not article.get("link") or not article.get("title"):
            skipped += 1
            continue

        images = article.get("images") or []
        summary = (article.get("summary") or "").strip()
        content = (article.get("content") or "").strip()
        companies = article.get("companies") or []
        tickers = _filter_tickers(companies)

        if not summary and content:
            summary = content[:300].strip()

        valid.append({
            "headline": article["title"],
            "summary": summary,
            "source_url": article["link"],
            "content": content or None,
            "image_url": images[0] if images else None,
            "categories": article.get("categories", []),
            "countries": article.get("countries", []),
            "tickers": tickers,
            "is_paywalled": False,
            "published_at": article.get("publishDate"),
        })

    if not valid:
        return {"saved": 0, "skipped": skipped}

    try:
        supabase_admin.table("news_articles").upsert(
            valid, on_conflict="source_url", ignore_duplicates=True
        ).execute()
        return {"saved": len(valid), "skipped": skipped}
    except Exception as e:
        logger.error(f"배치 저장 실패: {e}")
        return {"saved": 0, "skipped": skipped + len(valid)}


async def analyze_and_update(articles: list[dict]) -> None:
    """백그라운드에서 GenAI 분석 후 DB 업데이트 (성공한 결과만 저장)"""
    if not articles:
        return

    if _analysis_lock.locked():
        logger.info(f"[백그라운드] 분석 진행 중 → 스킵 ({len(articles)}개)")
        return

    async with _analysis_lock:
        await _do_analyze_and_update(articles)


def _db_update_article(update_data: dict, link: str) -> int:
    res = supabase_admin.table("news_articles").update(update_data).eq("source_url", link).execute()
    rows = len(res.data) if res.data else 0
    if rows == 0:
        res2 = supabase_admin.table("news_articles").update(update_data).eq("source_url", link + "/").execute()
        rows = len(res2.data) if res2.data else 0
    return rows


async def _do_analyze_and_update(articles: list[dict]) -> None:

    try:
        logger.info(f"[백그라운드] GenAI 분석 시작 → {len(articles)}개")
        enriched = await analyze_news_batch(articles)

        updated = 0
        failed = 0
        skipped = 0

        for article in enriched:
            enrichment = article.get("enrichment") or {}
            sentiment = enrichment.get("sentiment")
            link = (article.get("link") or article.get("source_url") or "").rstrip("/")

            if not link:
                skipped += 1
                continue

            if not isinstance(sentiment, dict):
                logger.warning(
                    f"[백그라운드] 스킵 (sentiment 없음): {link[:60]} | "
                    f"status={enrichment.get('status')} outcome={enrichment.get('outcome')} "
                    f"error={enrichment.get('error')}"
                )
                skipped += 1
                continue

            try:
                update_data = {
                    "sentiment_label": sentiment.get("label"),
                    "sentiment_score": sentiment.get("score"),
                    "summary_3lines": enrichment.get("summary_3lines") or [],
                    "xai": enrichment.get("xai"),
                }
                rows = await asyncio.to_thread(_db_update_article, update_data, link)
                logger.info(f"[DB] 업데이트: {link[:60]} → label={sentiment.get('label')} rows={rows}")
                updated += 1
            except Exception as e:
                failed += 1
                logger.error(f"[백그라운드] 업데이트 실패 ({link[:50]}): {e}")

        logger.info(f"[백그라운드] 완료 → 성공 {updated}개 / 실패 {failed}개 / 분석불가 {skipped}개")

    except Exception as e:
        logger.error(f"[백그라운드] 분석 파이프라인 오류: {type(e).__name__}: {e}")


def cleanup_old_content() -> None:
    """content NULL 또는 tickers 없는 기사 삭제"""
    try:
        supabase_admin.table("news_articles").delete().is_("content", "null").execute()
        supabase_admin.table("news_articles").delete().eq("tickers", "{}").execute()

        logger.info("[정리] content/tickers 없는 기사 삭제 완료")
    except Exception as e:
        logger.error(f"[정리] 삭제 실패: {e}")


async def collect_market_news() -> dict:
    """뉴스 수집 파이프라인 - 수집/저장 즉시 반환, 분석은 백그라운드"""
    logger.info("뉴스 수집 시작...")
    new_articles = await fetch_news_from_finlight()

    if not new_articles:
        logger.info("새 기사 없음 - 수집 종료")
        return {"saved": 0, "skipped": 0, "analyzing": 0}

    result = await asyncio.to_thread(save_news_to_db, new_articles)
    logger.info(f"저장 완료 → {result['saved']}개 저장, {result['skipped']}개 스킵")

    if result["saved"] > 0:
        async def _run_analysis() -> None:
            try:
                await analyze_and_update(new_articles)
            except Exception as e:
                logger.error(f"[백그라운드] 분석 파이프라인 예외: {type(e).__name__}: {e}", exc_info=True)

        asyncio.create_task(_run_analysis())
        logger.info(f"[백그라운드] GenAI 분석 예약 → {result['saved']}개")

    return {**result, "analyzing": result["saved"]}


def _fetch_unanalyzed(limit: int) -> list[dict]:
    result = supabase_admin.table("news_articles")\
        .select("id, source_url, headline, content, summary, tickers")\
        .is_("sentiment_label", "null")\
        .order("published_at", desc=True)\
        .limit(limit)\
        .execute()
    return result.data


async def reanalyze_unanalyzed(limit: int = 50, job_id: str | None = None) -> None:
    """sentiment가 NULL인 기사 재분석 (스케줄러용)"""
    try:
        if job_id:
            start_job(job_id)
        articles = await asyncio.to_thread(_fetch_unanalyzed, limit)
        if not articles:
            if job_id:
                finish_job(job_id, {"analyzed": 0, "message": "미분석 기사 없음"})
            return
        logger.info(f"[재분석] 미분석 기사 {len(articles)}개 발견 → 분석 시작")
        await analyze_and_update(articles)
        if job_id:
            finish_job(job_id, {"analyzed": len(articles)})
    except Exception as e:
        logger.error(f"[재분석] 오류: {type(e).__name__}: {e}")
        if job_id:
            fail_job(job_id, str(e))
