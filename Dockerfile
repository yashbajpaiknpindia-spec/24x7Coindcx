FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# Compatibility build for the older Render service whose Docker context is the repo root.
# It deliberately builds the fresh Binance Copy Intelligence source, not archived CoinDCX files.
COPY binance-copy-intelligence/bundle/ /tmp/bundle/
COPY binance-copy-intelligence/patches/ /tmp/patches/
RUN apt-get update \
    && apt-get install -y --no-install-recommends tar xz-utils nodejs \
    && cat /tmp/bundle/part* | base64 -d | tar -xJ -C /app \
    && python /tmp/patches/inspect_collector.py \
    && python /tmp/patches/apply_runtime_fixes.py \
    && python /tmp/patches/apply_multi_trader_mode.py \
    && python /tmp/patches/apply_portfolio_lab_api.py \
    && python /tmp/patches/apply_portfolio_lab_forecast.py \
    && python /tmp/patches/apply_portfolio_lab_daily.py \
    && python /tmp/patches/apply_portfolio_lab_markup.py \
    && python /tmp/patches/apply_portfolio_lab_ui.py \
    && python /tmp/patches/apply_portfolio_lab_daily_ui.py \
    && python /tmp/patches/apply_live_history_improvements.py \
    && python /tmp/patches/apply_position_history_dedupe.py \
    && python /tmp/patches/apply_frontend_cache_bust.py \
    && python /tmp/patches/inspect_runtime_contracts.py \
    && python -m py_compile /tmp/patches/apply_stability_coverage_ui.py \
    && python /tmp/patches/apply_stability_coverage_ui.py \
    && python -m py_compile /tmp/patches/apply_memory_guard.py \
    && python /tmp/patches/apply_memory_guard.py \
    && python -m py_compile /tmp/patches/apply_research_pages_and_filters.py \
    && python /tmp/patches/apply_research_pages_and_filters.py \
    && python -m py_compile /tmp/patches/apply_frontend_boot_recovery.py \
    && python /tmp/patches/apply_frontend_boot_recovery.py \
    && python -m py_compile /tmp/patches/apply_frontend_navigation_failsafe.py \
    && python /tmp/patches/apply_frontend_navigation_failsafe.py \
    && python -m py_compile /tmp/patches/apply_copier_safety_ranking.py \
    && python /tmp/patches/apply_copier_safety_ranking.py \
    && python -m py_compile /tmp/patches/apply_copier_forecast_gate.py \
    && python /tmp/patches/apply_copier_forecast_gate.py \
    && python -m py_compile /tmp/patches/apply_profit_tax_centre.py \
    && python /tmp/patches/apply_profit_tax_centre.py \
    && python -m py_compile /tmp/patches/apply_page_reliability_fixes.py \
    && python /tmp/patches/apply_page_reliability_fixes.py \
    && python -m py_compile /app/app.py \
    && nodejs --check /app/static/app.js \
    && apt-get purge -y nodejs \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/bundle \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && python /tmp/patches/verify_page_reliability.py \
    && rm -rf /tmp/patches
EXPOSE 10000
CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT:-10000}"]

# Rebuild: update Spot source period handling from apply_live_history_improvements.py.

# Rebuild: compact tables, stability-first risk ranking and explicit per-profile history coverage.
