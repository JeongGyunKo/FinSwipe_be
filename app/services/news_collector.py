import asyncio
import httpx
from app.core.config import settings
from app.core.supabase import supabase_admin

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
        # 숫자 포함 티커 제거 (아시아 증시: 2317, 005930 등)
        if not ticker.isalpha():
            continue
        # 암호화폐 티커 제거
        if ticker in CRYPTO_TICKERS:
            continue
        result.append(ticker)
    return result

# 다양한 쿼리로 content 있는 기사 최대화
COLLECTION_QUERIES = [
    "stock market earnings revenue",
    "Federal Reserve interest rates inflation",
    "tech stocks Apple Microsoft Google",
    "oil energy commodities",
    "IPO merger acquisition",
    "S&P 500 nasdaq dow jones",
    "forex dollar economy",
]

# Finlight 전용 클라이언트 (연결 풀 재사용)
_finlight_client: httpx.AsyncClient | None = None


def get_finlight_client() -> httpx.AsyncClient:
    global _finlight_client
    if _finlight_client is None:
        _finlight_client = httpx.AsyncClient(
            base_url=FINLIGHT_BASE_URL,
            headers={"X-API-KEY": settings.finlight_api_key},
            timeout=20.0,
        )
    return _finlight_client


async def _fetch_single_query(query: str, page_size: int = 100) -> list[dict]:
    """단일 쿼리로 Finlight 기사 수집"""
    try:
        response = await get_finlight_client().post(
            "/v2/articles",
            json={
                "query": query,
                "language": "en",
                "pageSize": page_size,
                "includeContent": True,
                "includeEntities": True,
            }
        )
        response.raise_for_status()
        return response.json().get("articles", [])
    except httpx.HTTPStatusError as e:
        print(f"[Finlight 오류] {query[:20]} HTTP {e.response.status_code}")
        return []
    except Exception as e:
        print(f"[Finlight 오류] {query[:20]} {type(e).__name__}: {e}")
        return []


async def fetch_news_from_finlight() -> list[dict]:
    """여러 쿼리 병렬 수집 → content 있는 새 기사만 반환"""
    results = await asyncio.gather(*[
        _fetch_single_query(q) for q in COLLECTION_QUERIES
    ])

    # 중복 제거 (link 기준)
    seen = set()
    all_articles = []
    for batch in results:
        for a in batch:
            link = a.get("link")
            if link and link not in seen:
                seen.add(link)
                all_articles.append(a)

    # content 없는 기사 제외
    with_content = [a for a in all_articles if a.get("content")]
    # ticker 없는 기사 제외
    with_tickers = [a for a in with_content if a.get("companies")]
    print(f"[Finlight] 수집 {len(all_articles)}개 → content {len(with_content)}개 → ticker 있음 {len(with_tickers)}개")

    # DB에 없는 새 기사만
    links = [a["link"] for a in with_tickers]
    new_links = await asyncio.to_thread(_filter_new_links, links)
    new_articles = [a for a in with_tickers if a.get("link") in new_links]
    print(f"[Finlight] 새 기사 {len(new_articles)}개")
    return new_articles


def _filter_new_links(links: list[str]) -> set[str]:
    """DB에 없는 링크만 반환 (청크 단위로 조회)"""
    if not links:
        return set()
    existing = set()
    chunk_size = 50
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
        print(f"기존 기사 조회 실패: {e}")
        return set(links)


def save_news_to_db(articles: list[dict]) -> dict:
    """뉴스 DB 배치 저장"""
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

        # summary 없으면 content 앞 300자로 대체
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
        # ignore_duplicates=True: 이미 존재하는 기사는 스킵 (분석 데이터 보호)
        supabase_admin.table("news_articles").upsert(
            valid, on_conflict="source_url", ignore_duplicates=True
        ).execute()
        return {"saved": len(valid), "skipped": skipped}
    except Exception as e:
        print(f"배치 저장 실패: {e}")
        return {"saved": 0, "skipped": skipped + len(valid)}


async def analyze_and_update(articles: list[dict]) -> None:
    """백그라운드에서 GenAI 분석 후 DB 업데이트 (성공한 결과만 저장)"""
    if not articles:
        return

    if _analysis_lock.locked():
        print(f"[백그라운드] 분석 진행 중 → 스킵 ({len(articles)}개)")
        return

    async with _analysis_lock:
        await _do_analyze_and_update(articles)


async def _do_analyze_and_update(articles: list[dict]) -> None:
    from app.services.analyzer import analyze_news_batch
    from app.services.translator import translate_article

    try:
        print(f"[백그라운드] GenAI 분석 시작 → {len(articles)}개")
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

            # 감성 분석 실패 시 DB 업데이트 안 함 (기존 데이터 보호)
            if not isinstance(sentiment, dict):
                status = enrichment.get("status")
                outcome = enrichment.get("outcome")
                error = enrichment.get("error")
                summary_count = len(enrichment.get("summary_3lines") or [])
                print(f"[백그라운드] 스킵 (sentiment 없음): {link[:60]}")
                print(f"  ↳ status={status} outcome={outcome} summary_count={summary_count} error={error}")
                skipped += 1
                continue

            try:
                headline = article.get("headline") or article.get("title") or ""
                summary_3lines = enrichment.get("summary_3lines") or []

                # DeepL 번역
                headline_ko, summary_3lines_ko = await translate_article(headline, summary_3lines)

                update_data = {
                    "sentiment_label": sentiment.get("label"),
                    "sentiment_score": sentiment.get("score"),
                    "summary_3lines": summary_3lines,
                    "xai": enrichment.get("xai"),
                    "headline_ko": headline_ko,
                    "summary_3lines_ko": summary_3lines_ko,
                }
                res = supabase_admin.table("news_articles").update(update_data).eq("source_url", link).execute()
                rows = len(res.data) if res.data else 0
                if rows == 0:
                    # trailing slash 버전으로 재시도
                    res2 = supabase_admin.table("news_articles").update(update_data).eq("source_url", link + "/").execute()
                    rows = len(res2.data) if res2.data else 0
                print(f"[DB] 업데이트: {link[:60]} → label={sentiment.get('label')} rows={rows}")
                updated += 1
            except Exception as e:
                failed += 1
                print(f"[백그라운드] 업데이트 실패 ({link[:50]}): {e}")

        print(f"[백그라운드] 완료 → 성공 {updated}개 / 실패 {failed}개 / 분석불가 {skipped}개")

    except Exception as e:
        print(f"[백그라운드] 분석 파이프라인 오류: {type(e).__name__}: {e}")


def cleanup_old_content() -> None:
    """48시간 지난 기사 삭제 + content NULL 기사 삭제"""
    try:
        from datetime import datetime, timezone, timedelta

        # 48시간 지난 기사 삭제
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        supabase_admin.table("news_articles")\
            .delete()\
            .lt("created_at", cutoff)\
            .execute()

        # content NULL인 기사 삭제
        supabase_admin.table("news_articles")\
            .delete()\
            .is_("content", "null")\
            .execute()

        # tickers 없는 기사 삭제
        supabase_admin.table("news_articles")\
            .delete()\
            .eq("tickers", "{}")\
            .execute()

        print("[정리] 48시간 이상 된 기사 및 content/tickers 없는 기사 삭제 완료")
    except Exception as e:
        print(f"[정리] 삭제 실패: {e}")


async def collect_market_news() -> dict:
    """뉴스 수집 파이프라인 - 수집/저장 즉시 반환, 분석은 백그라운드"""
    print("뉴스 수집 시작...")
    new_articles = await fetch_news_from_finlight()

    if not new_articles:
        print("새 기사 없음 - 수집 종료")
        return {"saved": 0, "skipped": 0, "analyzing": 0}

    result = await asyncio.to_thread(save_news_to_db, new_articles)
    print(f"저장 완료 → {result['saved']}개 저장, {result['skipped']}개 스킵")

    if result["saved"] > 0:
        task = asyncio.create_task(analyze_and_update(new_articles))
        task.add_done_callback(
            lambda t: print(f"[백그라운드] 태스크 오류: {t.exception()}") if t.exception() else None
        )
        print(f"[백그라운드] GenAI 분석 예약 → {result['saved']}개")

    return {**result, "analyzing": result["saved"]}


async def reanalyze_unanalyzed(limit: int = 50) -> None:
    """sentiment가 NULL인 기사 재분석 (스케줄러용)"""
    try:
        result = supabase_admin.table("news_articles")\
            .select("*")\
            .is_("sentiment_label", "null")\
            .order("published_at", desc=True)\
            .limit(limit)\
            .execute()
        articles = result.data
        if not articles:
            return
        print(f"[재분석] 미분석 기사 {len(articles)}개 발견 → 분석 시작")
        await analyze_and_update(articles)
    except Exception as e:
        print(f"[재분석] 오류: {type(e).__name__}: {e}")
