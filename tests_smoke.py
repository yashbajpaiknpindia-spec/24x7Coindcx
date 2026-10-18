"""Offline smoke tests: no CoinDCX API calls and no order submission."""
import os, tempfile
from pathlib import Path

# Set env before importing app modules (db engine is created at import time).
_tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp.close()
os.environ['DATABASE_URL'] = 'sqlite:///' + _tmp.name
os.environ['SECRET_KEY'] = 'smoke-test-secret-not-for-production-000000000000'
os.environ['ADMIN_USERNAME'] = 'smokeadmin'
os.environ['ADMIN_PASSWORD'] = 'smoke-password-not-for-production'
os.environ['COOKIE_SECURE'] = 'false'
os.environ['LIVE_TRADING_ENABLED'] = 'false'
os.environ.pop('COINDCX_API_KEY', None)
os.environ.pop('COINDCX_API_SECRET', None)

from fastapi.testclient import TestClient
from app.main import app

ROUTES = ['/dashboard','/markets','/strategy','/paper','/live','/orders','/positions','/analytics','/backtests','/journal','/settings']

def run():
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/', follow_redirects=False).status_code == 303
        assert client.get('/login').status_code == 200
        bad = client.post('/login', data={'username':'wrong','password':'wrong'})
        assert bad.status_code == 401
        login = client.post('/login', data={'username':'smokeadmin','password':'smoke-password-not-for-production'}, follow_redirects=False)
        assert login.status_code == 303
        for route in ROUTES:
            r = client.get(route)
            assert r.status_code == 200, f'{route}: {r.status_code} {r.text[:400]}'
        status = client.get('/api/paper-status')
        assert status.status_code == 200, status.text[:400]
        assert 'scan_universe_count' in status.json()
        # Start must persist an immediate run request, not just toggle the enabled flag.
        queued = client.post('/paper/start', follow_redirects=False)
        assert queued.status_code == 303
        from app.db import SessionLocal
        from app.core import read_config
        with SessionLocal() as db:
            cfg = read_config(db, 'strategy_config', {})
            assert cfg.get('paper_enabled') is True
            assert cfg.get('paper_cycle_requested_at'), cfg
        # live routes must not submit anything while environment gate is off.
        csrf = client.cookies.get('cdx_terminal_session')
        blocked = client.post('/live/arm', data={'confirmation':'ARM LIVE TRADING','csrf_token':'anything'}, follow_redirects=False)
        assert blocked.status_code == 403, f'CSRF gate not working: {blocked.status_code}'
        print('SMOKE TESTS PASSED: health, login, all UI routes, and live CSRF gate. No external APIs or real orders used.')

if __name__ == '__main__':
    try: run()
    finally:
        try: Path(_tmp.name).unlink()
        except OSError: pass
