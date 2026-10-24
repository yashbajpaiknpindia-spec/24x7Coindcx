# Binance Copy Intelligence — isolated app

This directory is isolated from the CoinDCX application at the repository root. Deploy it as a separate Render web service using this folder as the Docker context.

## Automatic workflow
- The scheduler is enabled by the Render environment configuration.
- Discovery runs in bounded batches; the scheduled jobs sync portfolio history and process trade-path analysis for queued portfolios.
- Periodic metrics such as 7D, 30D, and 365D MDD are displayed only when source-reported values are returned and stored. Missing periods must remain missing, not inferred from another window.
- Trade-path statistics depend on available trade timestamps and candle data. The system must report absent or incomplete source history instead of claiming all trades were analysed.
- Spot copy-trading discovery uses undocumented Binance website endpoints; successful deployment alone does not guarantee those endpoints return data.

## Optional Binance API environment variables
Set `BINANCE_API_KEY` and `BINANCE_API_SECRET` in Render Environment settings. Use a read-only key with IP restrictions. The app exposes `/api/config-status`, which returns only booleans indicating whether the environment variables exist. It never returns the key or secret and does not place trades. These credentials do not grant access to private history belonging to other lead traders.

## Database
When configured, `DATABASE_URL` is used for persistence. Without it, the SQLite fallback is local to the service container and is not durable across every redeploy/restart. Configure a dedicated PostgreSQL database before relying on long-term historical records; do not point this app at the CoinDCX app's database.

## Render
- Docker context: `binance-copy-intelligence`
- Dockerfile path: `binance-copy-intelligence/Dockerfile`
