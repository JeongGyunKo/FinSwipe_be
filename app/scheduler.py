import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.news_collector import collect_market_news, cleanup_old_content, reanalyze_unanalyzed

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _cleanup_async():
    """cleanup_old_content는 sync → 이벤트 루프 블로킹 방지를 위해 스레드에서 실행"""
    await asyncio.to_thread(cleanup_old_content)


def start_scheduler():
    if scheduler.running:
        return
    scheduler.add_job(
        collect_market_news,
        "interval",
        minutes=15,
        id="news_collector",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        reanalyze_unanalyzed,
        "interval",
        minutes=2,
        id="reanalyze_unanalyzed",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _cleanup_async,
        "interval",
        hours=6,
        id="content_cleanup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("스케줄러 시작 → 15분마다 뉴스 수집, 30분마다 미분석 재분석, 6시간마다 원문 정리")
