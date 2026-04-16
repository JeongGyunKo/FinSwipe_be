"""
Supabase tickers 테이블에 전체 티커 데이터 삽입
실행: python3 scripts/seed_tickers.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.supabase import supabase_admin
from app.services.ticker_names import TICKER_NAMES

# upsert — 중복 실행해도 안전
rows = [
    {"ticker": t, "corp": v["corp"], "ko": v["ko"]}
    for t, v in TICKER_NAMES.items()
]

BATCH = 500
total = 0
for i in range(0, len(rows), BATCH):
    batch = rows[i : i + BATCH]
    supabase_admin.table("ticker_names").upsert(batch, on_conflict="ticker").execute()
    total += len(batch)
    print(f"  {total}/{len(rows)} 완료")

print(f"\n총 {total}개 삽입/업데이트 완료")
