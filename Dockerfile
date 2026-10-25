FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# Compatibility build for the older Render service whose Docker context is the repo root.
# It deliberately builds the fresh Binance Copy Intelligence source, not archived CoinDCX files.
COPY binance-copy-intelligence/bundle/ /tmp/bundle/
COPY binance-copy-intelligence/patches/ /tmp/patches/
RUN apt-get update \
    && apt-get install -y --no-install-recommends tar xz-utils \
    && rm -rf /var/lib/apt/lists/* \
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
    && rm -rf /tmp/bundle /tmp/patches \
    && pip install --no-cache-dir -r /app/requirements.txt
EXPOSE 10000
CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:${PORT:-10000}"]

# Rebuild: update Spot source period handling from apply_live_history_improvements.py.
