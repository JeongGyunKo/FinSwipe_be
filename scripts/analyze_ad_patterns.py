"""
enrichment_results의 raw_text에서 광고 패턴을 분석하여 CSV로 출력합니다.
AI-News-Curation Supabase 프로젝트에 연결합니다.

사용법:
  $env:SUPABASE_URL="https://..."; $env:SUPABASE_SERVICE_KEY="..."; python scripts/analyze_ad_patterns.py
"""

import csv
import os
import sys
from urllib.parse import urlparse

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL 과 SUPABASE_SERVICE_KEY 환경변수를 설정해주세요.")
    sys.exit(1)

AD_PATTERNS = [
    "WHILE YOU'RE HERE",
    "Claim The Stock Ticker",
    "Is now the time to buy",
    "Will AI create the world's first trillionaire",
    "Our team just released a report",
    "Access our full analysis report here",
    "Get All 3 Stocks Here for FREE",
    "The Next Palantir",
    "Continue »",
    "Image source:",
    "Story Continues",
    "Different technology.",
    "If you missed Palantir",
    "This stock is still flying under the radar",
]


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return "unknown"


def find_ad_info(raw_text: str, pattern: str) -> dict:
    idx = raw_text.lower().find(pattern.lower())
    if idx == -1:
        return {}
    total = len(raw_text)
    ratio = round(idx / total, 3)
    start = max(0, idx - 20)
    end = min(total, idx + 100)
    snippet = raw_text[start:end].replace("\n", " ").strip()
    return {
        "char_index": idx,
        "total_chars": total,
        "position_ratio": ratio,
        "snippet": snippet,
    }


def fetch_all(client) -> list[dict]:
    results = []
    page_size = 100
    offset = 0
    while True:
        resp = client.table("enrichment_results") \
            .select("link, payload_json") \
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

    print("enrichment_results 전체 조회 중...")
    rows = fetch_all(client)
    print(f"총 {len(rows)}개 조회 완료\n")

    output_rows = []

    for row in rows:
        link = row.get("link") or ""
        payload = row.get("payload_json") or {}
        fetch_result = payload.get("fetch_result") or {}
        raw_text = fetch_result.get("raw_text") or ""

        if not raw_text or not link:
            continue

        domain = get_domain(link)
        found_any = False

        for pattern in AD_PATTERNS:
            if pattern.lower() in raw_text.lower():
                info = find_ad_info(raw_text, pattern)
                output_rows.append({
                    "domain": domain,
                    "url": link,
                    "ad_pattern": pattern,
                    "char_index": info.get("char_index", ""),
                    "total_chars": info.get("total_chars", ""),
                    "position_ratio": info.get("position_ratio", ""),
                    "snippet": info.get("snippet", ""),
                })
                found_any = True

        if not found_any:
            output_rows.append({
                "domain": domain,
                "url": link,
                "ad_pattern": "",
                "char_index": "",
                "total_chars": "",
                "position_ratio": "",
                "snippet": "",
            })

    output_path = "scripts/ad_analysis_result.csv"
    fieldnames = ["domain", "url", "ad_pattern", "char_index", "total_chars", "position_ratio", "snippet"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    ad_rows = [r for r in output_rows if r["ad_pattern"]]
    domains: dict = {}
    for r in ad_rows:
        d = r["domain"]
        p = r["ad_pattern"]
        ratio = r["position_ratio"]
        if d not in domains:
            domains[d] = {}
        if p not in domains[d]:
            domains[d][p] = []
        domains[d][p].append(float(ratio) if ratio != "" else 0)

    print(f"분석 완료 → {output_path}")
    print(f"광고 발견: {len(ad_rows)}건\n")
    print("=== 도메인별 광고 패턴 및 평균 위치 ===")
    for domain, patterns in sorted(domains.items()):
        print(f"\n[{domain}]")
        for pattern, ratios in patterns.items():
            avg = round(sum(ratios) / len(ratios), 3)
            print(f"  - '{pattern}' | 평균 위치: {avg * 100:.1f}% 지점 ({len(ratios)}건)")


if __name__ == "__main__":
    main()
