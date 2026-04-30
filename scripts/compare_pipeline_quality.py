"""
날짜별 enrichment_results 파이프라인 품질 비교 스크립트
어제 vs 오늘 데이터를 URL 중복 제거 후 비교합니다.

사용법:
  $env:SUPABASE_URL="https://..."; $env:SUPABASE_SERVICE_KEY="..."; python scripts/compare_pipeline_quality.py
"""

import csv
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수를 설정해주세요.")
    sys.exit(1)

AD_PATTERNS = [
    "Will AI create the world",
    "Our team just released a report",
    "Is now the time to buy",
    "Claim The Stock Ticker",
    "WHILE YOU'RE HERE",
    "The Next Palantir",
    "Get All 3 Stocks Here for FREE",
    "This stock is still flying under the radar",
    "If you missed Palantir",
    "Different technology.",
    "Access our full analysis report here",
    "Story Continues",
]


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return "unknown"


def check_ads(text: str) -> list[str]:
    return [p for p in AD_PATTERNS if p.lower() in text.lower()]


def fetch_range(client, start: str, end: str) -> list[dict]:
    results = []
    page_size = 100
    offset = 0
    while True:
        resp = client.table("enrichment_results") \
            .select("link, payload_json, analyzed_at") \
            .gte("analyzed_at", start) \
            .lt("analyzed_at", end) \
            .range(offset, offset + page_size - 1) \
            .execute()
        batch = resp.data or []
        results.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return results


def deduplicate(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for r in rows:
        link = r.get("link") or ""
        if link not in seen:
            seen.add(link)
            result.append(r)
    return result


def analyze_batch(rows: list[dict]) -> dict:
    total = len(rows)
    if total == 0:
        return {"total": 0}

    summary_ok = 0
    translation_ok = 0
    xai_ok = 0
    clean_filtered = 0
    ads_in_raw = 0
    ads_in_cleaned = 0
    remaining_ad_patterns: dict[str, int] = {}
    sentiments = {}
    confidences = []
    outcomes = {}

    for row in rows:
        payload = row.get("payload_json") or {}
        outcome = payload.get("analysis_outcome") or "unknown"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

        summary = payload.get("summary_3lines") or []
        if len(summary) == 3 and all(s.strip() for s in summary):
            summary_ok += 1

        localized = payload.get("localized") or {}
        loc_summary = localized.get("summary_3lines") or []
        if len(loc_summary) == 3:
            translation_ok += 1

        xai = payload.get("xai")
        if xai and xai.get("highlights"):
            xai_ok += 1

        status = payload.get("analysis_status") or ""
        if status == "clean_filtered":
            clean_filtered += 1

        sentiment = payload.get("sentiment") or {}
        label = sentiment.get("label") or "none"
        confidence = sentiment.get("confidence")
        sentiments[label] = sentiments.get(label, 0) + 1
        if confidence:
            confidences.append(confidence)

        raw_text = (payload.get("fetch_result") or {}).get("raw_text") or ""
        cleaned = payload.get("cleaned_text_preview") or ""

        if check_ads(raw_text):
            ads_in_raw += 1

        cleaned_ads = check_ads(cleaned)
        if cleaned_ads:
            ads_in_cleaned += 1
            for p in cleaned_ads:
                remaining_ad_patterns[p] = remaining_ad_patterns.get(p, 0) + 1

    avg_conf = round(sum(confidences) / len(confidences) * 100, 1) if confidences else 0

    return {
        "total": total,
        "success_rate": round(outcomes.get("success", 0) / total * 100, 1),
        "summary_rate": round(summary_ok / total * 100, 1),
        "translation_rate": round(translation_ok / total * 100, 1),
        "xai_rate": round(xai_ok / total * 100, 1),
        "avg_confidence": avg_conf,
        "clean_filtered": clean_filtered,
        "clean_filtered_rate": round(clean_filtered / total * 100, 1),
        "ads_in_raw": ads_in_raw,
        "ads_in_raw_rate": round(ads_in_raw / total * 100, 1),
        "ads_in_cleaned": ads_in_cleaned,
        "ads_in_cleaned_rate": round(ads_in_cleaned / total * 100, 1),
        "remaining_ad_patterns": remaining_ad_patterns,
        "sentiments": sentiments,
        "outcomes": outcomes,
    }


def print_comparison(label: str, data: dict):
    print(f"\n{'='*50}")
    print(f"  {label} (총 {data['total']}개)")
    print(f"{'='*50}")
    print(f"  분석 성공률:       {data['success_rate']}%")
    print(f"  요약 성공률:       {data['summary_rate']}%")
    print(f"  번역 성공률:       {data['translation_rate']}%")
    print(f"  XAI 성공률:        {data['xai_rate']}%")
    print(f"  평균 신뢰도:       {data['avg_confidence']}%")
    print(f"  clean_filtered:    {data['clean_filtered']}개 ({data['clean_filtered_rate']}%)")
    print(f"  원문 광고 잔존:    {data['ads_in_raw']}개 ({data['ads_in_raw_rate']}%)")
    print(f"  정제 후 광고:      {data['ads_in_cleaned']}개 ({data['ads_in_cleaned_rate']}%)")
    if data.get("remaining_ad_patterns"):
        print("  └ 잔존 광고 패턴:")
        for p, cnt in sorted(data["remaining_ad_patterns"].items(), key=lambda x: -x[1]):
            print(f"      - '{p}': {cnt}건")
    print(f"  감성 분포: {data['sentiments']}")


def main():
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    print("Supabase 연결 중...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("어제 데이터 조회 중...")
    yesterday_rows = deduplicate(fetch_range(client, yesterday_start, today_start))
    print(f"어제: {len(yesterday_rows)}개 (중복 제거 후)")

    print("오늘 데이터 조회 중...")
    today_rows = deduplicate(fetch_range(client, today_start, now.isoformat()))
    print(f"오늘: {len(today_rows)}개 (중복 제거 후)")

    yesterday_data = analyze_batch(yesterday_rows)
    today_data = analyze_batch(today_rows)

    print_comparison(f"이전 ({len(yesterday_rows)}개 / 어제)", yesterday_data)
    print_comparison(f"새로운 ({len(today_rows)}개 / 오늘)", today_data)

    metrics = [
        ("분석 성공률", "success_rate"),
        ("요약 성공률", "summary_rate"),
        ("번역 성공률", "translation_rate"),
        ("XAI 성공률", "xai_rate"),
        ("평균 신뢰도", "avg_confidence"),
        ("clean_filtered율", "clean_filtered_rate"),
        ("원문 광고 잔존율", "ads_in_raw_rate"),
        ("정제 후 광고율", "ads_in_cleaned_rate"),
    ]

    # 변화 요약 콘솔 출력
    print(f"\n{'='*50}")
    print("  어제 → 오늘 1차 → 오늘 2차 변화")
    print(f"{'='*50}")
    for label, key in metrics:
        v1 = yesterday_data.get(key, 0)
        v2 = first_data.get(key, 0)
        v3 = second_data.get(key, 0)
        print(f"  {label}: {v1}% → {v2}% → {v3}%")

    # CSV 저장
    csv_path = "scripts/compare_result.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["항목", "어제", "오늘_1차", "오늘_2차", "변화(어제→2차)"])
        writer.writeheader()
        for label, key in metrics:
            v1 = yesterday_data.get(key, 0)
            v2 = first_data.get(key, 0)
            v3 = second_data.get(key, 0)
            diff = round(v3 - v1, 1)
            writer.writerow({
                "항목": label,
                "어제": f"{v1}%",
                "오늘_1차": f"{v2}%",
                "오늘_2차": f"{v3}%",
                "변화(어제→2차)": f"{'+' if diff > 0 else ''}{diff}%",
            })
        # 잔존 광고 패턴
        writer.writerow({"항목": "--- 잔존 광고 패턴 (오늘 2차) ---", "어제": "", "오늘_1차": "", "오늘_2차": "", "변화(어제→2차)": ""})
        for p, cnt in sorted((second_data.get("remaining_ad_patterns") or {}).items(), key=lambda x: -x[1]):
            writer.writerow({"항목": p, "어제": "", "오늘_1차": "", "오늘_2차": f"{cnt}건", "변화(어제→2차)": ""})

    print(f"\n비교 결과 저장 → {csv_path}")


if __name__ == "__main__":
    main()
