FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY bundle/ /tmp/bundle/
COPY patches/ /tmp/patches/
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
    && python -m py_compile /tmp/patches/apply_profit_tax_centre.py \
    && python /tmp/patches/apply_profit_tax_centre.py \
    && python /tmp/patches/apply_frontend_cache_bust.py \
    && python /tmp/patches/inspect_runtime_contracts.py \
    && python -m py_compile /tmp/patches/apply_dual_investment_intelligence.py \
    && python /tmp/patches/apply_dual_investment_intelligence.py \
    && python -m py_compile /tmp/patches/fix_dual_investment_intelligence.py \
    && python /tmp/patches/fix_dual_investment_intelligence.py \
    && python -m py_compile /tmp/patches/enable_dual_investment_background_worker.py \
    && python /tmp/patches/enable_dual_investment_background_worker.py \
    && python -m py_compile /tmp/patches/limit_dual_investment_settlement_horizon.py \
    && python /tmp/patches/limit_dual_investment_settlement_horizon.py \
    && python -m py_compile /app/app.py \
    && nodejs --check /app/static/app.js \
    && apt-get purge -y nodejs \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/bundle /tmp/patches \
    && pip install --no-cache-dir -r /app/requirements.txt
EXPOSE 10000
CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT:-10000}"]
