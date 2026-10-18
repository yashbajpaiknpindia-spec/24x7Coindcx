"""CoinDCX REST client. Public data methods are read-only; private methods require explicit keys."""
import hashlib, hmac, json, os, time
from typing import Any
import requests

BASE = 'https://api.coindcx.com'
PUBLIC = 'https://public.coindcx.com'
TIMEOUT = (4, 12)

class CoinDCXError(RuntimeError):
    pass

class CoinDCXClient:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        self.api_key = api_key if api_key is not None else os.getenv('COINDCX_API_KEY', '')
        self.api_secret = api_secret if api_secret is not None else os.getenv('COINDCX_API_SECRET', '')
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'CoinDCXStrategyTerminal/1.0', 'Accept': 'application/json'})

    @property
    def credentials_present(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def public_get(self, path: str, params: dict[str, Any] | None = None, base: str = BASE):
        try:
            r = self.session.get(base + path, params=params, timeout=TIMEOUT)
            if r.status_code == 429:
                raise CoinDCXError('CoinDCX API rate limit (HTTP 429). Reduce polling and retry after cooldown.')
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            raise CoinDCXError(f'Public API request failed: {exc}') from exc

    def signed_post(self, path: str, body: dict[str, Any] | None = None):
        if not self.credentials_present:
            raise CoinDCXError('CoinDCX API credentials are not configured in server environment variables.')
        payload_obj = dict(body or {})
        payload_obj['timestamp'] = int(time.time() * 1000)
        payload = json.dumps(payload_obj, separators=(',', ':'), ensure_ascii=False)
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {'Content-Type': 'application/json', 'X-AUTH-APIKEY': self.api_key, 'X-AUTH-SIGNATURE': signature}
        try:
            r = self.session.post(BASE + path, data=payload, headers=headers, timeout=TIMEOUT)
            if r.status_code == 429:
                raise CoinDCXError('CoinDCX API rate limit (HTTP 429).')
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and (data.get('status') == 401 or str(data.get('code')) in {'401', '4001'}):
                raise CoinDCXError(f'CoinDCX authentication/API error: {data}')
            return data
        except (requests.RequestException, ValueError) as exc:
            raise CoinDCXError(f'Authenticated API request failed: {exc}') from exc

    def spot_tickers(self):
        data = self.public_get('/exchange/ticker')
        return data if isinstance(data, list) else []

    def spot_market_details(self):
        data = self.public_get('/exchange/v1/markets_details')
        return data if isinstance(data, list) else []

    def spot_markets(self):
        data = self.public_get('/exchange/v1/markets')
        return data if isinstance(data, list) else []

    def spot_candles(self, pair: str, interval: str = '1h', limit: int = 500):
        # API returns descending time order; normalize to ascending for strategy calculation.
        data = self.public_get('/market_data/candles', params={'pair': pair, 'interval': interval, 'limit': min(int(limit), 1000)})
        if not isinstance(data, list): return []
        return sorted(data, key=lambda x: float(x.get('time', 0)))

    def spot_orderbook(self, pair: str, depth: int = 50):
        return self.public_get('/market_data/orderbook', params={'pair': pair, 'depth': depth})

    def spot_trades(self, pair: str, limit: int = 100):
        return self.public_get('/market_data/trade_history', params={'pair': pair, 'limit': min(limit, 500)})

    def futures_active_instruments(self, margin: str = 'USDT'):
        return self.public_get('/exchange/v1/derivatives/futures/data/active_instruments', params={'margin_currency_short_name[]': margin})

    def futures_instrument(self, pair: str, margin: str = 'USDT'):
        return self.public_get('/exchange/v1/derivatives/futures/data/instrument', params={'pair': pair, 'margin_currency_short_name': margin})

    def futures_prices(self):
        data = self.public_get('/market_data/v3/current_prices/futures/rt', base=PUBLIC)
        # The documented endpoint returns {ts, vs, prices:{'B-BTC_USDT':{...}}}.
        # Older parsing treated ts/vs/prices themselves as price rows, leaving all
        # futures snapshots with missing prices. Also accept older `data` wrappers.
        if isinstance(data, dict) and isinstance(data.get('prices'), dict):
            prices = data['prices']
            return [dict(v, mkt=(v.get('mkt') or k)) for k, v in prices.items() if isinstance(v, dict)]
        if isinstance(data, dict) and 'data' in data:
            data = data['data']
            if isinstance(data, dict) and isinstance(data.get('prices'), dict):
                prices = data['prices']
                return [dict(v, mkt=(v.get('mkt') or k)) for k, v in prices.items() if isinstance(v, dict)]
        if isinstance(data, list): return data
        if isinstance(data, dict): return [dict(v, mkt=k) if isinstance(v, dict) else {'mkt': k, 'ls': v} for k,v in data.items()]
        return []

    def futures_orderbook(self, pair: str, depth: int = 50):
        safe_depth = depth if depth in {10, 20, 50} else 50
        return self.public_get(f'/market_data/v3/orderbook/{pair}-futures/{safe_depth}', base=PUBLIC)

    def futures_trades(self, pair: str):
        return self.public_get('/exchange/v1/derivatives/futures/data/trades', params={'pair': pair})

    def futures_candles(self, pair: str, resolution: int = 60, limit: int = 500):
        # Public futures candle API uses epoch seconds and resolution in minutes.
        now = int(time.time())
        start = now - (max(1, min(limit, 1000)) * resolution * 60)
        data = self.public_get('/market_data/candlesticks', params={'pair': pair, 'from': start, 'to': now, 'resolution': resolution, 'pcode': 'f'}, base=PUBLIC)
        # Futures candles use {"s":"ok","data":[...]}; reject explicit error statuses.
        if isinstance(data, dict):
            if str(data.get('s', 'ok')).lower() not in ('ok', 'success', 'true'):
                return []
            data = data.get('data', [])
        if not isinstance(data, list): return []
        normalized = []
        for row in data:
            d = dict(row)
            d.setdefault('time', d.get('t') or d.get('timestamp') or d.get('T'))
            d.setdefault('open', d.get('o')); d.setdefault('high', d.get('h')); d.setdefault('low', d.get('l'))
            d.setdefault('close', d.get('c')); d.setdefault('volume', d.get('v') or d.get('q'))
            if d.get('time') is not None:
                # Futures endpoint can return second timestamps; normalize to ms.
                try:
                    if float(d['time']) < 10_000_000_000: d['time'] = float(d['time']) * 1000
                except Exception: pass
            normalized.append(d)
        return sorted(normalized, key=lambda x: float(x.get('time', 0)))

    def spot_balances(self):
        return self.signed_post('/exchange/v1/users/balances', {})

    def user_info(self):
        return self.signed_post('/exchange/v1/users/info', {})

    def futures_positions(self, size: int = 100):
        return self.signed_post('/exchange/v1/derivatives/futures/positions', {'page':'1', 'size': str(size), 'margin_currency_short_name':['USDT']})

    def futures_orders(self, size: int = 100):
        return self.signed_post('/exchange/v1/derivatives/futures/orders', {'status':'open,filled,partially_filled,cancelled,rejected', 'side':'buy', 'page':'1', 'size':str(size), 'margin_currency_short_name':['USDT']})


    def spot_order_status(self, order_id: str | None = None, client_order_id: str | None = None):
        body = {}
        if order_id and str(order_id).isdigit(): body['id'] = int(order_id)
        elif client_order_id: body['client_order_id'] = client_order_id
        elif order_id: body['client_order_id'] = str(order_id)
        else: raise CoinDCXError('Spot order status requires an exchange order ID or client order ID.')
        return self.signed_post('/exchange/v1/orders/status', body)

    def spot_trade_history(self, from_id: int | None = None, limit: int = 500, sort: str = 'asc'):
        # Official account trade-history schema documents from_id/limit/sort. Do not send
        # undocumented timestamp filters which may be rejected or silently ignored.
        direction = 'desc' if str(sort).lower() == 'desc' else 'asc'
        body: dict[str, Any] = {'limit': min(max(int(limit), 1), 500), 'sort': direction}
        if from_id is not None: body['from_id'] = int(from_id)
        return self.signed_post('/exchange/v1/orders/trade_history', body)

    def futures_order_list(self, side: str, status: str = 'open,filled,partially_filled,cancelled,rejected,untriggered', size: int = 100, page: int = 1):
        return self.signed_post('/exchange/v1/derivatives/futures/orders', {
            'status': status, 'side': side, 'page': str(page), 'size': str(min(max(int(size), 1), 1000)),
            'margin_currency_short_name': ['USDT']})

    def futures_trade_history(self, pair: str, order_id: str | None, from_date: str, to_date: str, page: int = 1, size: int = 100):
        body: dict[str, Any] = {'pair': pair, 'from_date': from_date, 'to_date': to_date,
                                'page': str(page), 'size': str(min(max(int(size), 1), 1000)),
                                'margin_currency_short_name': ['USDT']}
        if order_id: body['order_id'] = str(order_id)
        return self.signed_post('/exchange/v1/derivatives/futures/trades', body)

    def futures_wallets(self):
        return self.signed_post('/exchange/v1/derivatives/futures/wallets', {})

    def futures_transactions(self, size: int = 1000, page: int = 1, stage: str = 'all'):
        # Endpoint accepts a paginated authenticated POST with stage all/default/funding.
        return self.signed_post('/exchange/v1/derivatives/futures/positions/transactions', {
            'stage': stage, 'page': str(page), 'size': str(min(max(int(size), 1), 1000)),
            'margin_currency_short_name': ['USDT']})

    def submit_spot_order(self, market: str, side: str, quantity: float, order_type: str = 'market_order', price: float | None = None, ecode: str | None = None, client_order_id: str | None = None):
        body: dict[str, Any] = {'market': market, 'side': side, 'order_type': order_type, 'total_quantity': quantity}
        if price is not None and order_type == 'limit_order': body['price_per_unit'] = price
        if ecode: body['ecode'] = ecode
        if client_order_id: body['client_order_id'] = client_order_id
        return self.signed_post('/exchange/v1/orders/create', body)

    def submit_futures_order(self, pair: str, side: str, quantity: float, leverage: int = 1, order_type: str = 'market_order', price: float | None = None, margin: str = 'USDT', client_order_id: str | None = None):
        order: dict[str, Any] = {'side': side, 'pair': pair, 'order_type': order_type, 'total_quantity': quantity,
                                 'leverage': int(leverage), 'margin_currency_short_name': margin,
                                 'notification': 'no_notification', 'hidden': False, 'post_only': False}
        if price is not None and order_type == 'limit_order': order['price'] = price
        if client_order_id: order['client_order_id'] = client_order_id
        return self.signed_post('/exchange/v1/derivatives/futures/orders/create', {'order': order})
