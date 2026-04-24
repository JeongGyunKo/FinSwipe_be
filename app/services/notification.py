import json
import logging
import httpx
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

# FCM V1 API 엔드포인트
FCM_V1_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


async def _get_access_token(service_account_json: str) -> str | None:
    """서비스 계정 JSON으로 OAuth 2.0 액세스 토큰 발급"""
    try:
        import google.auth
        import google.auth.transport.requests
        from google.oauth2 import service_account

        info = json.loads(service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        return credentials.token
    except Exception as e:
        logger.error(f"[알림] 액세스 토큰 발급 실패: {e}")
        return None


def _get_tokens_for_tickers(tickers: list[str]) -> list[str]:
    """관심 종목을 등록한 사용자들의 FCM 토큰 조회"""
    if not tickers:
        return []
    try:
        result = supabase_admin.table("user_profiles") \
            .select("id") \
            .overlaps("tickers", tickers) \
            .execute()

        user_ids = [row["id"] for row in result.data or []]
        if not user_ids:
            return []

        tokens_result = supabase_admin.table("device_tokens") \
            .select("token") \
            .in_("user_id", user_ids) \
            .execute()

        return [row["token"] for row in tokens_result.data or []]
    except Exception as e:
        logger.error(f"[알림] 티커 기반 토큰 조회 실패: {e}")
        return []


async def send_push(
    *,
    title: str,
    body: str,
    service_account_json: str,
    tokens: list[str],
    data: dict | None = None,
) -> None:
    """FCM V1 API로 푸시 알림 발송"""
    if not service_account_json:
        logger.warning("[알림] FCM_SERVICE_ACCOUNT_JSON 미설정 → 알림 스킵")
        return
    if not tokens:
        logger.info("[알림] 발송 대상 토큰 없음 → 스킵")
        return

    access_token = await _get_access_token(service_account_json)
    if not access_token:
        return

    info = json.loads(service_account_json)
    project_id = info.get("project_id")
    url = FCM_V1_URL.format(project_id=project_id)

    success = 0
    failed = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for token in tokens:
            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": {k: str(v) for k, v in (data or {}).items()},
                }
            }
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    success += 1
                else:
                    failed += 1
                    logger.warning(f"[알림] FCM 발송 실패: {resp.status_code} {resp.text[:100]}")
            except Exception as e:
                failed += 1
                logger.error(f"[알림] 발송 오류: {e}")

    logger.info(f"[알림] 발송 완료 → 성공 {success}개 / 실패 {failed}개")


async def notify_ticker_article(
    *,
    headline: str,
    tickers: list[str],
    service_account_json: str,
) -> None:
    """관심 종목 기사 알림 발송 - 해당 종목 관심 등록 사용자에게만 발송"""
    tokens = _get_tokens_for_tickers(tickers)
    if not tokens:
        return

    ticker_str = ", ".join(tickers[:3])
    await send_push(
        title=f"📈 {ticker_str} 관련 새 뉴스",
        body=headline[:80] + ("..." if len(headline) > 80 else ""),
        service_account_json=service_account_json,
        tokens=tokens,
        data={"type": "ticker_article", "tickers": ",".join(tickers)},
    )
