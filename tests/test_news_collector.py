from app.services.news_collector import _filter_tickers


def test_filter_tickers_keeps_us_stocks():
    companies = [{"ticker": "AAPL"}, {"ticker": "MSFT"}, {"ticker": "GOOGL"}]
    assert _filter_tickers(companies) == ["AAPL", "MSFT", "GOOGL"]


def test_filter_tickers_removes_crypto():
    companies = [{"ticker": "BTC"}, {"ticker": "AAPL"}, {"ticker": "ETH"}]
    assert _filter_tickers(companies) == ["AAPL"]


def test_filter_tickers_removes_numeric_asian():
    companies = [{"ticker": "005930"}, {"ticker": "MSFT"}, {"ticker": "2317"}]
    assert _filter_tickers(companies) == ["MSFT"]


def test_filter_tickers_removes_alphanumeric():
    companies = [{"ticker": "123ABC"}, {"ticker": "NVDA"}]
    assert _filter_tickers(companies) == ["NVDA"]


def test_filter_tickers_empty_input():
    assert _filter_tickers([]) == []


def test_filter_tickers_no_ticker_field():
    companies = [{"name": "Apple Inc"}, {"ticker": "AAPL"}]
    assert _filter_tickers(companies) == ["AAPL"]


def test_filter_tickers_empty_ticker_string():
    companies = [{"ticker": ""}, {"ticker": "TSLA"}]
    assert _filter_tickers(companies) == ["TSLA"]


def test_filter_tickers_case_insensitive():
    companies = [{"ticker": "aapl"}, {"ticker": "btc"}]
    assert _filter_tickers(companies) == ["AAPL"]
