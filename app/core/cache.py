import time
from typing import Any

_store: dict[str, tuple[Any, float]] = {}
_access_count = 0
_CLEANUP_INTERVAL = 20  # 20번 접근마다 만료 항목 정리


def _maybe_cleanup() -> None:
    global _access_count
    _access_count += 1
    if _access_count % _CLEANUP_INTERVAL == 0:
        now = time.time()
        expired = [k for k, (_, exp) in _store.items() if now > exp]
        for k in expired:
            del _store[k]


def cache_get(key: str) -> Any | None:
    _maybe_cleanup()
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _store[key]
        return None
    return value


def cache_set(key: str, value: Any, ttl_seconds: int = 30) -> None:
    _store[key] = (value, time.time() + ttl_seconds)


def cache_delete(key: str) -> None:
    _store.pop(key, None)
