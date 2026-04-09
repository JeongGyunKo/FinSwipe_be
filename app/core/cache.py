import time
from typing import Any

_store: dict[str, tuple[Any, float]] = {}


def cache_get(key: str) -> Any | None:
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
