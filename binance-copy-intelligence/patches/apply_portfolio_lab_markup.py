from pathlib import Path
root=Path("/app")
hp=root/"templates"/"index.html"
h=hp.read_text()
old='    <button class="nav-link" data-view="traders"><span class="nav-ico">◎</span> Trader universe</button>\n'
new=old+'    <button class="nav-link" data-view="portfolio-lab"><span class="nav-ico">↗</span> Portfolio Lab</button>\n'
if 'data-view="portfolio-lab"' not in h:
    if h.count(old)!=1: raise RuntimeError("Portfolio Lab nav anchor not unique")
    h=h.replace(old,new,1)
section="""    <section class="view" id="view-portfolio-lab">
      <div class="section-heading"><div><div class="eyebrow">TRADE-BEHAVIOUR AUDIT · INVESTMENT SCENARIO</div><h2>Portfolio Lab</h2><p>Compare recorded trading behaviour, open official portfolio pages, inspect past trades, and model hypothetical outcomes.</p></div><span class="tag blue">PAPER RESEARCH · NO ORDERS</span></div>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">SCENARIO INPUTS</div><h3>Investment value & assumptions</h3></div><span class="tag purple">EDITABLE</span></div>
        <div class="field-row"><label>Market<select id="pl-market"><option value="FUTURES">Futures</option><option value="SPOT">Spot</option></select></label>
        <label>Investment (USD)<input id="pl-capital" type="number" min="1" step="1" value="250"></label>
        <label>Margin allocated per position (%)<input id="pl-allocation" type="number" min="0.5" max="100" step="0.5" value="10"></label>
        <label>Extra copy execution drag (bps of notional)<input id="pl-cost-bps" type="number" min="0" max="500" value="5"></label>
        <label>Forecast horizon<select id="pl-horizon"><option value="7">7 days</option><option value="14">14 days</option><option value="30">30 days</option></select></label></div>
        <div class="button-row"><button id="pl-run-forecast" class="btn primary">Rank expected future returns</button><button id="pl-refresh" class="btn secondary">Refresh portfolios</button></div>
        <p class="help-text">Forecasts resample recent stored closed-trade outcomes; the 10th–90th percentile is an uncertainty range, not a guarantee. Funding, exact copy fills, and live open exposure may be unavailable.</p>
      </article>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">UPCOMING DAYS · MODEL ESTIMATE</div><h3>Expected-return ranking</h3></div><span class="tag gray" id="pl-rank-meta">Not calculated</span></div>
        <div id="pl-rank-note" class="notice-box">Choose your investment value and run the forecast. Profiles without sufficient history will be shown separately.</div>
        <div class="table-scroll"><table><thead><tr><th>Rank</th><th>Portfolio / official page</th><th>Expected PnL</th><th>Median PnL</th><th>10th–90th percentile</th><th>Observed leverage</th><th>Historical modelled PnL</th><th>Max DD</th><th>Trades used</th><th>Inspect</th></tr></thead><tbody id="pl-rank-rows"><tr><td colspan="10" class="empty-state">Run a forecast to rank available evidence.</td></tr></tbody></table></div>
        <h3 style="margin-top:20px">Insufficient recent evidence</h3><div class="table-scroll"><table><thead><tr><th>Portfolio / official page</th><th>Usable trades</th><th>Source ROI</th><th>Reason no forecast</th><th>Inspect</th></tr></thead><tbody id="pl-unready-rows"><tr><td colspan="5" class="empty-state">Not loaded.</td></tr></tbody></table></div>
      </article>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">SELECTED PORTFOLIO</div><h3 id="pl-detail-title">Choose a portfolio to inspect</h3></div><span class="tag blue">NO LIVE ORDERS</span></div>
        <div id="pl-official-link" class="run-sub">Official portfolio link will appear here.</div>
        <div class="kpi-grid"><article class="kpi-card"><div class="kpi-head"><span>Stored positions</span></div><div id="pl-kpi-trades" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>MAE/MFE coverage</span></div><div id="pl-kpi-paths" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Recorded closed PnL</span></div><div id="pl-kpi-pnl" class="kpi-value">—</div></article><article class="kpi-card"><div class="kpi-head"><span>Cumulative-sequence DD</span></div><div id="pl-kpi-dd" class="kpi-value">—</div></article></div>
        <div id="pl-behaviour" class="metric-explain"></div>
        <h3 style="margin-top:20px">Cumulative recorded closed-trade PnL</h3><p class="help-text">Close-time sequence, not account equity or true drawdown across overlapping positions.</p><canvas id="pl-curve" width="900" height="220" style="width:100%;height:220px;background:#0b1420;border:1px solid #263849;border-radius:12px"></canvas>
        <h3 style="margin-top:20px">Source-reported performance snapshots</h3><div class="table-scroll"><table><thead><tr><th>Captured (UTC)</th><th>Period</th><th>ROI</th><th>PnL</th><th>MDD</th><th>Win rate</th><th>Copier PnL</th></tr></thead><tbody id="pl-snapshot-rows"><tr><td colspan="7" class="empty-state">Select a portfolio.</td></tr></tbody></table></div>
        <h3 style="margin-top:20px">Trade behaviour & past positions</h3><p id="pl-trade-coverage" class="help-text">Entry/exit time, reported leverage, MAE, MFE, path coverage and hypothetical single-trade PnL are shown where data exists.</p>
        <div class="table-scroll"><table><thead><tr><th>Close / status</th><th>Symbol</th><th>Side</th><th>Entry time / price</th><th>Exit price</th><th>Leverage</th><th>Margin mode</th><th>Close PnL</th><th>Reported ROI</th><th>MAE</th><th>MFE</th><th>Time to MAE / MFE</th><th>Path status</th><th>Illustrative PnL</th></tr></thead><tbody id="pl-trade-rows"><tr><td colspan="14" class="empty-state">Select a portfolio to load trades.</td></tr></tbody></table></div>
        <div class="button-row"><button id="pl-trades-prev" class="btn secondary" disabled>← Previous page</button><button id="pl-trades-next" class="btn secondary" disabled>Next page →</button><span id="pl-trades-page" class="help-text"></span></div>
        <div id="pl-model-notes" class="notice-box"></div>
        <h3 style="margin-top:20px">Day-by-day hypothetical return distribution</h3><div class="table-scroll"><table><thead><tr><th>Day</th><th>Expected cumulative PnL</th><th>Median</th><th>10th percentile</th><th>90th percentile</th><th>Expected return</th></tr></thead><tbody id="pl-daily-forecast"><tr><td colspan="6" class="empty-state">Run a forecast and select a portfolio.</td></tr></tbody></table></div>
      </article>
      <article class="panel"><div class="panel-header"><div><div class="eyebrow">SAVED PORTFOLIOS</div><h3>Official links & data coverage</h3></div><span id="pl-profile-meta" class="tag gray">Loading</span></div><div class="table-scroll"><table><thead><tr><th>Portfolio</th><th>Official Binance page</th><th>Source ROI</th><th>Source MDD</th><th>Source win rate</th><th>Stored positions</th><th>MAE/MFE</th><th>History status</th><th>Inspect</th></tr></thead><tbody id="pl-profile-rows"><tr><td colspan="9" class="empty-state">Loading profiles…</td></tr></tbody></table></div></article>
    </section>

"""
if 'id="view-portfolio-lab"' not in h:
    anchor='    <section class="view" id="view-reports">\n'
    if h.count(anchor)!=1: raise RuntimeError("Portfolio Lab section anchor not unique")
    h=h.replace(anchor,section+anchor,1)
hp.write_text(h)
print("Portfolio Lab markup installed")
