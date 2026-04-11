"""
ticker_names 테이블 시드 스크립트
실행: python -m scripts.seed_ticker_names
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.supabase import supabase_admin
from app.services.ticker_names import TICKER_NAMES


def seed():
    rows = [
        {"ticker": ticker, "corp": names["corp"], "ko": names["ko"]}
        for ticker, names in TICKER_NAMES.items()
    ]

    result = supabase_admin.table("ticker_names").upsert(rows, on_conflict="ticker").execute()
    print(f"완료: {len(rows)}개 티커 저장됨")
    return result


if __name__ == "__main__":
    seed()
