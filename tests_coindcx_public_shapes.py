"""Offline regression for documented CoinDCX futures market data response shapes."""
from app.coindcx import CoinDCXClient, PUBLIC

def run():
    client = CoinDCXClient(api_key="", api_secret="")
    calls = []
    def fake_public_get(path, params=None, base="https://api.coindcx.com"):
        calls.append((path, params, base))
        if path == "/market_data/v3/current_prices/futures/rt":
            return {"ts": 1780000000000, "vs": 1, "prices": {
                "B-BTC_USDT": {"mkt": "BTCUSDT", "ls": "65000", "v": "100"},
                "B-ETH_USDT": {"mkt": "ETHUSDT", "ls": "3200", "v": "200"}}}
        if path == "/market_data/candlesticks":
            return {"s": "ok", "data": [
                {"open": 100, "high": 103, "low": 99, "close": 102,
                 "volume": 10, "time": 1780000000}]}
        raise AssertionError(path)
    client.public_get = fake_public_get
    prices = client.futures_prices()
    assert len(prices) == 2, prices
    assert {x["mkt"] for x in prices} == {"BTCUSDT", "ETHUSDT"}, prices
    candles = client.futures_candles("B-BTC_USDT", resolution=60, limit=1)
    assert len(candles) == 1, candles
    assert candles[0]["close"] == 102
    assert candles[0]["time"] == 1780000000000
    assert calls[0][2] == PUBLIC
    print("PASS: nested futures prices and the {s,data} candle wrapper parse correctly.")

if __name__ == "__main__": run()
