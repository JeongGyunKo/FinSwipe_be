from app.services.analyzer import _parse_storage_payload, _unavailable
from app.core.cache import cache_get, cache_set, cache_delete


# ── analyzer tests ────────────────────────────────────────────

def test_unavailable_structure():
    result = _unavailable("test reason")
    assert result["status"] == "unavailable"
    assert result["outcome"] == "fatal_failure"
    assert result["sentiment"] is None
    assert result["summary_3lines"] == []
    assert result["error"]["code"] == "server_unavailable"
    assert result["error"]["message"] == "test reason"


def test_parse_storage_payload_with_sentiment():
    enrichment = {
        "analysis_status": "completed",
        "analysis_outcome": "success",
        "sentiment": {"label": "positive", "score": 85.0, "confidence": 0.9},
        "summary_3lines": ["line1", "line2", "line3"],
        "article_mixed": {"is_mixed": False},
    }
    result = _parse_storage_payload(enrichment)
    assert result["sentiment"]["label"] == "positive"
    assert result["sentiment"]["score"] == 85.0
    assert len(result["summary_3lines"]) == 3
    assert result["error"] is None
    assert result["is_mixed"] is False


def test_parse_storage_payload_no_sentiment():
    enrichment = {
        "analysis_status": "failed",
        "analysis_outcome": "failure",
        "sentiment": {},
        "summary_3lines": [],
    }
    result = _parse_storage_payload(enrichment)
    assert result["sentiment"] is None


def test_parse_storage_payload_summary_dict_format():
    enrichment = {
        "sentiment": {"label": "neutral", "score": 0.0, "confidence": 0.5},
        "summary_3lines": [
            {"text": "line1"},
            {"line": "line2"},
            {"content": "line3"},
        ],
    }
    result = _parse_storage_payload(enrichment)
    assert result["summary_3lines"] == ["line1", "line2", "line3"]


def test_parse_storage_payload_mixed_summary_format():
    enrichment = {
        "sentiment": {"label": "negative", "score": -50.0, "confidence": 0.8},
        "summary_3lines": ["string line", {"text": "dict line"}],
    }
    result = _parse_storage_payload(enrichment)
    assert result["summary_3lines"] == ["string line", "dict line"]


# ── cache tests ────────────────────────────────────────────

def test_cache_set_and_get():
    cache_set("test_key", {"data": 123}, ttl_seconds=60)
    result = cache_get("test_key")
    assert result == {"data": 123}


def test_cache_miss_returns_none():
    assert cache_get("nonexistent_key") is None


def test_cache_delete():
    cache_set("delete_me", "value", ttl_seconds=60)
    cache_delete("delete_me")
    assert cache_get("delete_me") is None


def test_cache_expired():
    import time
    cache_set("expire_test", "value", ttl_seconds=0)
    time.sleep(0.01)
    assert cache_get("expire_test") is None
