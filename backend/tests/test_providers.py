"""Provider adapters parse the documented response shapes (mocked HTTP; no live calls)."""
import httpx
import pytest
import respx

from marketpilot.data.providers.alpaca import AlpacaProvider
from marketpilot.data.providers.base import ProviderError, ProviderNotConfigured, parse_ts, validate_bar
from marketpilot.data.providers.massive import MassiveProvider
from marketpilot.data.models import Bar
from datetime import datetime, timezone

DATA = "https://data.alpaca.markets"


def alp():
    return AlpacaProvider("KEY", "SECRET", client=httpx.AsyncClient())


def test_alpaca_requires_keys_and_paper_reference_host():
    with pytest.raises(ProviderNotConfigured):
        AlpacaProvider(None, None)
    with pytest.raises(ProviderError):
        AlpacaProvider("k", "s", reference_url="https://api.alpaca.markets")


def test_parse_ts_variants():
    assert parse_ts("2026-11-18T14:30:00.123456789Z") == datetime(2026, 11, 18, 14, 30, 0, 123456, tzinfo=timezone.utc)
    assert parse_ts(1763476200000) == datetime.fromtimestamp(1763476200, tz=timezone.utc)
    assert parse_ts(1763476200000000000) == datetime.fromtimestamp(1763476200, tz=timezone.utc)


def test_validate_bar_rejects_corrupt():
    t = datetime.now(timezone.utc)
    assert validate_bar(Bar(t, 10, 11, 9, 10.5, 100))
    assert not validate_bar(Bar(t, 10, 9, 11, 10, 100))  # high < low
    assert not validate_bar(Bar(t, 0, 11, 9, 10, 100))


@pytest.mark.asyncio
@respx.mock
async def test_alpaca_bars_pagination_and_sip_history():
    route = respx.get(f"{DATA}/v2/stocks/bars").mock(side_effect=[
        httpx.Response(200, json={"bars": {"AAPL": [{"t": "2026-11-16T05:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "n": 3, "vw": 1.4}]},
                                  "next_page_token": "abc"}),
        httpx.Response(200, json={"bars": {"AAPL": [{"t": "2026-11-17T05:00:00Z", "o": 1.5, "h": 2.5, "l": 1.0, "c": 2.0, "v": 12}]},
                                  "next_page_token": None}),
    ])
    p = alp()
    out = await p.get_bars(["aapl"], "1Day", datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert [b.c for b in out["AAPL"]] == [1.5, 2.0]
    first = route.calls[0].request.url.params
    assert first["feed"] == "sip" and first["adjustment"] == "split"
    assert route.calls[1].request.url.params["page_token"] == "abc"
    assert route.calls[0].request.headers["APCA-API-KEY-ID"] == "KEY"


@pytest.mark.asyncio
@respx.mock
async def test_alpaca_snapshot_parsing():
    respx.get(f"{DATA}/v2/stocks/snapshots").mock(return_value=httpx.Response(200, json={"MSFT": {
        "latestTrade": {"t": "2026-11-18T15:00:00Z", "p": 410.5, "s": 100},
        "latestQuote": {"t": "2026-11-18T15:00:01Z", "bp": 410.4, "bs": 2, "ap": 410.6, "as": 3},
        "dailyBar": {"o": 405, "h": 412, "l": 404, "c": 410.5, "v": 1e6, "vw": 409},
        "prevDailyBar": {"c": 400.0}}}))
    snap = (await alp().get_snapshots(["MSFT"]))["MSFT"]
    assert snap.last_price == 410.5 and snap.prev_close == 400.0 and snap.feed == "alpaca:iex"
    assert snap.change_pct == pytest.approx(2.625) and snap.spread_bps == pytest.approx(4.87, abs=0.01)


@pytest.mark.asyncio
@respx.mock
async def test_alpaca_retries_429_and_reports_auth_errors():
    respx.get(f"{DATA}/v1beta1/screener/stocks/movers").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"gainers": [{"symbol": "X", "percent_change": 9.1, "change": 1, "price": 12}], "losers": []}),
    ])
    mv = await alp().get_movers(5)
    assert mv["gainers"][0].symbol == "X"
    respx.get(f"{DATA}/v1beta1/news").mock(return_value=httpx.Response(403, text="forbidden"))
    with pytest.raises(ProviderError):
        await alp().get_news(["X"])


def test_alpaca_stream_message_parsing():
    ev = AlpacaProvider._parse_stream_msg({"T": "t", "S": "AAPL", "p": 190.1, "s": 5, "t": "2026-11-18T15:00:00Z"})
    assert ev.kind == "trade" and ev.data["price"] == 190.1
    q = AlpacaProvider._parse_stream_msg({"T": "q", "S": "AAPL", "bp": 190, "ap": 190.2, "bs": 1, "as": 2, "t": "2026-11-18T15:00:00Z"})
    assert q.kind == "quote" and q.data["ask"] == 190.2
    with pytest.raises(ProviderError):
        AlpacaProvider._parse_stream_msg({"T": "error", "code": 406, "msg": "connection limit exceeded"})


def test_quality_labels_distinguish_feeds():
    assert alp().quality().label == "Real-time (IEX only)"
    assert AlpacaProvider("k", "s", feed="sip").quality().label == "Real-time (consolidated)"
    assert MassiveProvider("k").quality().label == "Delayed 15 min"


@pytest.mark.asyncio
@respx.mock
async def test_massive_aggs_and_snapshot():
    respx.get(url__regex=r"https://api\.massive\.com/v2/aggs/ticker/SPY/range/1/day/.*").mock(return_value=httpx.Response(200, json={
        "results": [{"t": 1763442000000, "o": 600, "h": 605, "l": 598, "c": 603, "v": 5e7}]}))
    respx.get("https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers").mock(return_value=httpx.Response(200, json={
        "tickers": [{"ticker": "SPY", "day": {"o": 600, "h": 606, "l": 599, "c": 604, "v": 1e7}, "prevDay": {"c": 600},
                     "lastTrade": {"p": 604.2, "t": 1763478000000000000}, "lastQuote": {"p": 604.1, "P": 604.3, "s": 1, "S": 2}}]}))
    p = MassiveProvider("KEY", client=httpx.AsyncClient())
    bars = await p.get_bars(["SPY"], "1Day", datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 18, tzinfo=timezone.utc))
    assert bars["SPY"][0].c == 603
    snap = (await p.get_snapshots(["SPY"]))["SPY"]
    assert snap.last_price == 604.2 and snap.bid == 604.1 and snap.ask == 604.3 and snap.feed == "massive:delayed"
