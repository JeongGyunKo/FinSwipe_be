"""
Supabase ticker_names 테이블에 전체 티커 데이터 삽입
실행: python3 scripts/seed_tickers.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.supabase import supabase_admin
from app.services.ticker_names import TICKER_NAMES

rows = [
    {"ticker": t, "corp": v["corp"], "ko": v["ko"]}
    for t, v in TICKER_NAMES.items()
]

BATCH = 500
total = 0
failed = 0

for i in range(0, len(rows), BATCH):
    batch = rows[i : i + BATCH]
    try:
        supabase_admin.table("ticker_names").upsert(batch, on_conflict="ticker").execute()
        total += len(batch)
        print(f"  {total}/{len(rows)} 완료")
    except Exception as e:
        failed += len(batch)
        print(f"  오류 (batch {i}~{i+BATCH}): {e}")

print(f"\n완료: {total}개 성공 / {failed}개 실패")
