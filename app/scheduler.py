from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.news_collector import collect_market_news

scheduler = AsyncIOScheduler()


def start_scheduler():
    if scheduler.running:
        return
    scheduler.add_job(
        collect_market_news,
        "interval",
        minutes=15,
        id="news_collector",
        replace_existing=True
    )
    scheduler.start()
    print("스케줄러 시작 → 15분마다 뉴스 자동 수집")
