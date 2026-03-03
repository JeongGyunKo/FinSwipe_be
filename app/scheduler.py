from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.news_collector import collect_market_news

scheduler = AsyncIOScheduler()

def start_scheduler():
    # 15분마다 자동 수집 (Finnhub 뉴스 업데이트 주기 고려)
    scheduler.add_job(
        collect_market_news,
        "interval",
        minutes=15,
        id="news_collector"
    )
    scheduler.start()
    print("스케줄러 시작 → 15분마다 뉴스 자동 수집")