from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_real_ip(request: Request) -> str:
    """리버스 프록시(Zeabur 등) 뒤에서 실제 클라이언트 IP 추출.
    X-Forwarded-For의 첫 번째 값을 사용하고, 없으면 직접 연결 IP로 폴백."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_get_real_ip)
