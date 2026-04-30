"""
오늘 생성된 enrichment_results payload_json 파이프라인 품질 분석 스크립트

사용법:
  $env:SUPABASE_URL="https://..."; $env:SUPABASE_SERVICE_KEY="..."; python scripts/analyze_pipeline_quality.py
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
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


def check_ads_in_text(text: str) -> list[str]:
    found = []
    for p in AD_PATTERNS:
        if p.lower() in text.lower():
            found.append(p)
    return found


def analyze_stage_statuses(stages: list[dict]) -> dict:
    result = {}
    for s in stages:
        result[s["stage"]] = s["status"]
    return result


def fetch_today(client) -> list[dict]:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    results = []
    page_size = 100
    offset = 0
    while True:
        resp = client.table("enrichment_results") \
            .select("link, payload_json, analyzed_at") \
            .gte("analyzed_at", today_start) \
            .range(offset, offset + page_size - 1) \
            .execute()
        batch = resp.data or []
        results.extend(batch)
        print(f"  조회 중... {len(results)}개")
        if len(batch) < page_size:
            break
        offset += page_size
    return results


def main():
    print("Supabase 연결 중...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("오늘 enrichment_results 조회 중...")
    rows = fetch_today(client)
    total = len(rows)
    print(f"총 {total}개 조회 완료\n")

    if total == 0:
        print("오늘 데이터 없음.")
        return

    # 집계 변수
    outcomes = {}
    analysis_statuses = {}
    summary_success = 0
    summary_empty = 0
    sentiment_labels = {}
    confidence_list = []
    translation_success = 0
    translation_empty = 0
    xai_success = 0
    xai_none = 0
    clean_filtered = 0
    ads_remaining = 0
    false_positive_clean = 0  # 실제 본문인데 필터된 케이스

    csv_rows = []

    for row in rows:
        link = row.get("link") or ""
        payload = row.get("payload_json") or {}
        domain = get_domain(link)

        outcome = payload.get("analysis_outcome") or "unknown"
        status = payload.get("analysis_status") or "unknown"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        analysis_statuses[status] = analysis_statuses.get(status, 0) + 1

        # clean_filtered 체크
        if status == "clean_filtered":
            clean_filtered += 1
            raw_text = (payload.get("fetch_result") or {}).get("raw_text") or ""
            # 실제 본문인데 필터된 케이스 (StockStory 등)
            if len(raw_text) > 500 and not any(
                p.lower() in raw_text.lower() for p in ["WHILE YOU'RE HERE", "Will AI create", "The Next Palantir"]
            ):
                false_positive_clean += 1

        # 요약 품질
        summary = payload.get("summary_3lines") or []
        if len(summary) == 3 and all(s.strip() for s in summary):
            summary_success += 1
        else:
            summary_empty += 1

        # 감성 분석
        sentiment = payload.get("sentiment") or {}
        label = sentiment.get("label") or "none"
        confidence = sentiment.get("confidence")
        sentiment_labels[label] = sentiment_labels.get(label, 0) + 1
        if confidence is not None:
            confidence_list.append(confidence)

        # 번역 품질
        localized = payload.get("localized") or {}
        loc_summary = localized.get("summary_3lines") or []
        if len(loc_summary) == 3:
            translation_success += 1
        else:
            translation_empty += 1

        # XAI
        xai = payload.get("xai")
        if xai and xai.get("highlights"):
            xai_success += 1
        else:
            xai_none += 1

        # 광고 잔존 여부
        raw_text = (payload.get("fetch_result") or {}).get("raw_text") or ""
        cleaned_preview = payload.get("cleaned_text_preview") or ""
        ads_in_raw = check_ads_in_text(raw_text)
        ads_in_cleaned = check_ads_in_text(cleaned_preview)
        if ads_in_cleaned:
            ads_remaining += 1

        # 스테이지별 상태
        stages = payload.get("stage_statuses") or []
        stage_map = analyze_stage_statuses(stages)

        csv_rows.append({
            "domain": domain,
            "url": link,
            "outcome": outcome,
            "status": status,
            "summary_lines": len(summary),
            "sentiment_label": label,
            "confidence": round(confidence, 3) if confidence else "",
            "translation_ok": "O" if len(loc_summary) == 3 else "X",
            "xai_ok": "O" if xai and xai.get("highlights") else "X",
            "ads_in_raw": ", ".join(ads_in_raw) if ads_in_raw else "",
            "ads_in_cleaned": ", ".join(ads_in_cleaned) if ads_in_cleaned else "",
            "clean_stage": stage_map.get("clean", ""),
            "summarize_stage": stage_map.get("summarize", ""),
        })

    # CSV 저장
    output_path = "scripts/pipeline_quality_report.csv"
    fieldnames = [
        "domain", "url", "outcome", "status",
        "summary_lines", "sentiment_label", "confidence",
        "translation_ok", "xai_ok",
        "ads_in_raw", "ads_in_cleaned",
        "clean_stage", "summarize_stage",
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    avg_confidence = round(sum(confidence_list) / len(confidence_list), 3) if confidence_list else 0

    # 콘솔 출력
    print("=" * 60)
    print(f"[파이프라인 품질 분석] 오늘 총 {total}개 기사")
    print("=" * 60)

    print("\n[분석 결과 (outcome)]")
    for k, v in sorted(outcomes.items(), key=lambda x: -x[1]):
        pct = round(v / total * 100, 1)
        print(f"  {k}: {v}개 ({pct}%)")

    print("\n[분석 상태 (status)]")
    for k, v in sorted(analysis_statuses.items(), key=lambda x: -x[1]):
        pct = round(v / total * 100, 1)
        print(f"  {k}: {v}개 ({pct}%)")

    print("\n[요약 품질]")
    print(f"  성공 (3줄): {summary_success}개 ({round(summary_success/total*100,1)}%)")
    print(f"  실패 (비어있음): {summary_empty}개 ({round(summary_empty/total*100,1)}%)")

    print("\n[감성 분석]")
    for k, v in sorted(sentiment_labels.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}개")
    print(f"  평균 신뢰도: {avg_confidence * 100:.1f}%")

    print("\n[번역 품질]")
    print(f"  성공: {translation_success}개 ({round(translation_success/total*100,1)}%)")
    print(f"  실패: {translation_empty}개 ({round(translation_empty/total*100,1)}%)")

    print("\n[XAI]")
    print(f"  성공: {xai_success}개 ({round(xai_success/total*100,1)}%)")
    print(f"  없음: {xai_none}개 ({round(xai_none/total*100,1)}%)")

    print("\n[정제 품질]")
    print(f"  clean_filtered (전체 제거): {clean_filtered}개 ({round(clean_filtered/total*100,1)}%)")
    print(f"  └ false positive 의심 (본문 있는데 필터됨): {false_positive_clean}개")
    print(f"  정제 후 광고 잔존: {ads_remaining}개 ({round(ads_remaining/total*100,1)}%)")

    print(f"\n분석 완료 → {output_path}")


if __name__ == "__main__":
    main()
