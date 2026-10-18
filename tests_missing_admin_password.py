"""Offline regression: a missing ADMIN_PASSWORD must not crash the web service."""
import os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["SECRET_KEY"] = "test-secret-very-long-not-production-123456"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = ""
os.environ["COOKIE_SECURE"] = "false"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["AUTO_LIVE_TRADING_ENABLED"] = "false"
os.environ.pop("COINDCX_API_KEY", None); os.environ.pop("COINDCX_API_SECRET", None)
from app.main import app

def run():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json().get("admin_auth_configured") is False, health.json()
        assert client.get("/login").status_code == 200
        locked = client.post("/login", data={"username":"admin", "password":"anything"})
        assert locked.status_code == 503, locked.status_code
        print("MISSING-PASSWORD REGRESSION PASSED: startup/health remain available; login fails closed.")

if __name__ == "__main__":
    try: run()
    finally:
        try: Path(_tmp.name).unlink()
        except OSError: pass
