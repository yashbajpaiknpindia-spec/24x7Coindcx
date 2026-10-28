from pathlib import Path

APP_PATH = Path("/app/app.py")
source = APP_PATH.read_text()

if "BINANCE_DUAL_INVESTMENT_BACKGROUND_WORKER_V1" not in source:
    source += r'''

# BINANCE_DUAL_INVESTMENT_BACKGROUND_WORKER_V1
# Runtime-only, server-side background scanner. Explicitly opt-in using
# DI_BACKGROUND_SCAN_ENABLED=true; build/smoke-test imports never start network scans.
import os as _di_bg_os
import threading as _di_bg_threading
import time as _di_bg_time

def _di_background_scan_loop():
    interval = max(300, min(3600, int(_di_bg_os.environ.get("DI_BACKGROUND_SCAN_INTERVAL_SECONDS", "300"))))
    while True:
        try:
            result = _di_scan(
                amount_usdt=_di_bg_os.environ.get("DI_PAPER_NOTIONAL_USDT", "150"),
                direction_filter="both",
                max_distance=_di_bg_os.environ.get("DI_MAX_TARGET_DISTANCE_PCT", "5"),
                max_tail_loss_pct=_di_bg_os.environ.get("DI_MAX_TAIL_LOSS_PCT", "3"),
            )
            app.logger.info(
                "dual_investment_background_scan_completed scan_id=%s status=%s offers=%s selected=%s errors=%s settled_proxy_updates=%s",
                result.get("scan_id"), result.get("status"), result.get("products_fetched"),
                result.get("selected_count"), len(result.get("errors") or []),
                result.get("settled_proxy_updates"),
            )
        except Exception:
            app.logger.exception("dual_investment_background_scan_failed")
        _di_bg_time.sleep(interval)

if (_di_bg_os.environ.get("DI_BACKGROUND_SCAN_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")):
    _di_bg_thread = _di_bg_threading.Thread(
        target=_di_background_scan_loop,
        name="dual-investment-paper-scanner",
        daemon=True,
    )
    _di_bg_thread.start()
'''
    APP_PATH.write_text(source)

print("Installed opt-in background Dual Investment paper scanner; no subscription or order capability added.")
