from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.news_collector import collect_market_news, cleanup_old_content, reanalyze_unanalyzed

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
    scheduler.add_job(
        reanalyze_unanalyzed,
        "interval",
        minutes=30,
        id="reanalyze_unanalyzed",
        replace_existing=True
    )
    scheduler.add_job(
        cleanup_old_content,
        "interval",
        hours=6,
        id="content_cleanup",
        replace_existing=True
    )
    scheduler.start()
    print("스케줄러 시작 → 15분마다 뉴스 수집, 30분마다 미분석 재분석, 6시간마다 원문 정리")
