"""
파이프라인 품질 보고서 생성기
날짜 범위를 입력받아 enrichment_results를 분석하고 HTML 보고서를 생성합니다.

사용법:
  $env:SUPABASE_URL="https://..."; $env:SUPABASE_SERVICE_KEY="..."; python scripts/generate_report.py
  날짜 입력 예시: 2026-04-23 (하루) 또는 2026-04-20 ~ 2026-04-24 (범위)
"""

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
    "Will AI create the world", "Our team just released a report",
    "Is now the time to buy", "Claim The Stock Ticker",
    "WHILE YOU'RE HERE", "The Next Palantir",
    "Get All 3 Stocks Here for FREE", "This stock is still flying under the radar",
    "If you missed Palantir", "Different technology.",
    "Access our full analysis report here", "Story Continues",
]


def check_ads(text):
    return [p for p in AD_PATTERNS if p.lower() in (text or "").lower()]


def fetch_range(client, start: str, end: str) -> list[dict]:
    results, offset = [], 0
    while True:
        resp = client.table("enrichment_results") \
            .select("link, payload_json, analyzed_at") \
            .gte("analyzed_at", start).lt("analyzed_at", end) \
            .range(offset, offset + 99).execute()
        batch = resp.data or []
        results.extend(batch)
        if len(batch) < 100:
            break
        offset += 100

    # URL 기준 중복 제거 (최신 항목 유지)
    seen, deduped = set(), []
    for r in sorted(results, key=lambda x: x.get("analyzed_at") or "", reverse=True):
        link = r.get("link") or ""
        if link and link not in seen:
            seen.add(link)
            deduped.append(r)
    return deduped


def analyze(rows: list[dict]) -> dict:
    total = len(rows)
    if total == 0:
        return {"total": 0}

    summary_ok = translation_ok = xai_ok = clean_filtered = ads_raw = ads_cleaned = 0
    sentiments, confidences, remaining_ads, outcomes = {}, [], {}, {}

    for row in rows:
        p = row.get("payload_json") or {}
        outcome = p.get("analysis_outcome", "unknown")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

        s = p.get("summary_3lines") or []
        if len(s) == 3 and all(x.strip() for x in s):
            summary_ok += 1

        loc = (p.get("localized") or {}).get("summary_3lines") or []
        if len(loc) == 3:
            translation_ok += 1

        xai = p.get("xai")
        if xai and xai.get("highlights"):
            xai_ok += 1

        if p.get("analysis_status") == "clean_filtered":
            clean_filtered += 1

        sent = p.get("sentiment") or {}
        label = sent.get("label") or "none"
        conf = sent.get("confidence")
        sentiments[label] = sentiments.get(label, 0) + 1
        if conf and conf < 1.0:  # 1.0은 비정상 기본값이므로 제외
            confidences.append(conf)

        raw = (p.get("fetch_result") or {}).get("raw_text") or ""
        cleaned = p.get("cleaned_text_preview") or ""
        if check_ads(raw):
            ads_raw += 1
        ca = check_ads(cleaned)
        if ca:
            ads_cleaned += 1
            for pat in ca:
                remaining_ads[pat] = remaining_ads.get(pat, 0) + 1

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
        "ads_raw_rate": round(ads_raw / total * 100, 1),
        "ads_cleaned_rate": round(ads_cleaned / total * 100, 1),
        "remaining_ads": remaining_ads,
        "sentiments": sentiments,
        "outcomes": outcomes,
    }


def bar(val, max_val=100):
    pct = min(val / (max_val or 1) * 100, 100)
    return f'<div style="background:#334155;border-radius:4px;height:6px;width:100%;margin-top:4px"><div style="background:#38bdf8;border-radius:4px;height:6px;width:{pct}%"></div></div>'


def cell_color(val, key):
    good = {"success_rate", "summary_rate", "translation_rate", "xai_rate", "avg_confidence"}
    bad = {"clean_filtered_rate", "ads_raw_rate", "ads_cleaned_rate"}
    if key in good:
        return "#4ade80" if val >= 90 else "#facc15" if val >= 70 else "#f87171"
    if key in bad:
        return "#4ade80" if val == 0 else "#facc15" if val <= 15 else "#f87171"
    return "#e2e8f0"


def generate_html(batches: list[tuple[str, dict]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    metrics = [
        ("분석 성공률", "success_rate"),
        ("요약 성공률", "summary_rate"),
        ("번역 성공률", "translation_rate"),
        ("XAI 성공률", "xai_rate"),
        ("평균 신뢰도", "avg_confidence"),
        ("clean_filtered율", "clean_filtered_rate"),
        ("원문 광고 잔존율", "ads_raw_rate"),
        ("정제 후 광고 잔존율", "ads_cleaned_rate"),
    ]

    # 헤더
    headers = "".join(f"<th>{label} ({d['total']}개)</th>" for label, d in batches)

    # 메트릭 행
    rows_html = ""
    for m_label, key in metrics:
        cells = ""
        base_val = batches[0][1].get(key, 0) if batches else 0
        for i, (_, d) in enumerate(batches):
            val = d.get(key, 0)
            c = cell_color(val, key)
            diff = ""
            if i > 0:
                delta = round(val - base_val, 1)
                sign = "+" if delta > 0 else ""
                diff_color = "#4ade80" if delta > 0 else "#f87171" if delta < 0 else "#94a3b8"
                diff = f' <span style="font-size:11px;color:{diff_color}">({sign}{delta}%)</span>'
            cells += f'<td style="text-align:center;padding:10px"><span style="color:{c};font-weight:bold;font-size:16px">{val}%</span>{diff}{bar(val)}</td>'
        rows_html += f"<tr><td style='padding:10px 16px;font-weight:500;border-right:1px solid #334155'>{m_label}</td>{cells}</tr>"

    # 잔존 광고 (마지막 배치 기준)
    last_data = batches[-1][1] if batches else {}
    ad_rows = ""
    for pat, cnt in sorted((last_data.get("remaining_ads") or {}).items(), key=lambda x: -x[1]):
        ad_rows += f"<tr><td style='padding:8px 16px'>{pat}</td><td style='padding:8px;text-align:center;color:#f87171;font-weight:bold'>{cnt}건</td></tr>"
    if not ad_rows:
        ad_rows = "<tr><td colspan='2' style='padding:12px;color:#4ade80;text-align:center'>잔존 광고 없음 ✅</td></tr>"

    # 감성 분포
    sent_rows = ""
    for label, d in batches:
        sents = d.get("sentiments") or {}
        total = d.get("total") or 1
        sent_rows += f"<tr><td style='padding:8px 16px;font-weight:500'>{label}</td>"
        for s, sc in [("positive", "#4ade80"), ("neutral", "#94a3b8"), ("negative", "#f87171"), ("none", "#475569")]:
            cnt = sents.get(s, 0)
            pct = round(cnt / total * 100, 1)
            sent_rows += f"<td style='text-align:center;padding:8px;color:{sc}'>{cnt}개<br><span style=\"font-size:11px\">({pct}%)</span></td>"
        sent_rows += "</tr>"

    # 이슈 요약
    issues = []
    for _, d in batches:
        if d.get("clean_filtered_rate", 0) > 0:
            issues.append(f"❌ clean_filtered {d['clean_filtered_rate']}% 발생 중")
        if d.get("xai_rate", 100) < 80:
            issues.append(f"❌ XAI 성공률 {d['xai_rate']}% — confidence=1.0 버그 의심")
        if d.get("ads_cleaned_rate", 0) > 10:
            issues.append(f"⚠️ 정제 후 광고 {d['ads_cleaned_rate']}% 잔존")
    if not issues:
        issues.append("✅ 전체 파이프라인 정상 작동 중")
    issues_html = "".join(f"<p style='margin:6px 0'>{i}</p>" for i in issues)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>FinSwipe 파이프라인 보고서</title>
<style>
  * {{ box-sizing: border-box }}
  body {{ font-family: 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:32px }}
  h1 {{ color:#38bdf8; font-size:22px; margin:0 0 4px }}
  .sub {{ color:#64748b; font-size:13px; margin-bottom:32px }}
  h2 {{ color:#7dd3fc; font-size:15px; margin:28px 0 12px; border-left:3px solid #38bdf8; padding-left:10px }}
  table {{ width:100%; border-collapse:collapse; background:#1e293b; border-radius:12px; overflow:hidden; margin-bottom:20px; font-size:14px }}
  th {{ background:#0f172a; padding:12px 16px; text-align:center; color:#7dd3fc; font-size:13px; font-weight:600 }}
  th:first-child {{ text-align:left }}
  tr {{ border-bottom:1px solid #1e293b }}
  tr:last-child {{ border-bottom:none }}
  tr:hover {{ background:#263348 }}
  .card {{ background:#1e293b; border-radius:12px; padding:20px; margin-bottom:20px }}
</style>
</head>
<body>
<h1>📊 FinSwipe 파이프라인 품질 보고서</h1>
<div class="sub">생성: {now} | 총 {sum(d['total'] for _, d in batches)}개 기사 분석</div>

<h2>📈 항목별 품질 비교</h2>
<table>
  <thead><tr><th>항목</th>{headers}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<h2>💬 감성 분포</h2>
<table>
  <thead><tr><th>기간</th><th style="color:#4ade80">Positive</th><th style="color:#94a3b8">Neutral</th><th style="color:#f87171">Negative</th><th style="color:#475569">None</th></tr></thead>
  <tbody>{sent_rows}</tbody>
</table>

<h2>⚠️ 잔존 광고 패턴 (최근 배치 기준)</h2>
<table>
  <thead><tr><th style="text-align:left">패턴</th><th>건수</th></tr></thead>
  <tbody>{ad_rows}</tbody>
</table>

<h2>🔍 이슈 요약</h2>
<div class="card">{issues_html}</div>
</body>
</html>"""


def parse_date_input(s: str):
    s = s.strip()
    if "~" in s:
        parts = s.split("~")
        start = datetime.strptime(parts[0].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(parts[1].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    else:
        start = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
    return start, end


def main():
    print("Supabase 연결 중...")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("\n날짜를 입력하세요.")
    print("  단일 날짜: 2026-04-23")
    print("  범위:      2026-04-22 ~ 2026-04-24")
    print("  (엔터 = 어제+오늘 자동 비교)\n")

    raw = input("날짜 입력: ").strip()

    batches = []

    if not raw:
        # 기본: 어제 vs 오늘
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        print("어제 데이터 조회 중...")
        yesterday_rows = fetch_range(client, yesterday_start.isoformat(), today_start.isoformat())
        print(f"어제: {len(yesterday_rows)}개")

        print("오늘 데이터 조회 중...")
        today_rows = fetch_range(client, today_start.isoformat(), now.isoformat())
        print(f"오늘: {len(today_rows)}개")

        batches = [
            (f"어제 ({yesterday_start.strftime('%m/%d')})", analyze(yesterday_rows)),
            (f"오늘 ({today_start.strftime('%m/%d')})", analyze(today_rows)),
        ]
    elif "~" in raw:
        # 범위: 날짜별로 각각 분석
        parts = raw.split("~")
        start = datetime.strptime(parts[0].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(parts[1].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        current = start
        while current <= end:
            next_day = current + timedelta(days=1)
            print(f"{current.strftime('%Y-%m-%d')} 조회 중...")
            rows = fetch_range(client, current.isoformat(), next_day.isoformat())
            print(f"  {len(rows)}개")
            if rows:
                batches.append((current.strftime("%m/%d"), analyze(rows)))
            current = next_day
    else:
        start, end = parse_date_input(raw)
        print(f"{raw} 데이터 조회 중...")
        rows = fetch_range(client, start.isoformat(), end.isoformat())
        print(f"{len(rows)}개")
        batches = [(raw, analyze(rows))]

    if not batches:
        print("데이터 없음.")
        return

    html = generate_html(batches)
    output = "scripts/pipeline_report.html"
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n보고서 생성 완료 → {output}")


if __name__ == "__main__":
    main()
