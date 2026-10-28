from pathlib import Path
import re

APP_PATH = Path("/app/app.py")
source = APP_PATH.read_text()

_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#090d16">
<title>Dual Investment Lab | Binance Intel</title>
<style>
:root{color-scheme:dark;--bg:#090d16;--panel:#111927;--panel2:#151f30;--line:#26344a;--text:#edf3ff;--muted:#9eacc2;--subtle:#71819b;--blue:#8ab9ff;--cyan:#69dfda;--green:#5bd4a0;--red:#ff8e98;--amber:#f1c56e;--shadow:0 18px 48px rgba(0,0,0,.22)}
*{box-sizing:border-box;min-width:0}
html{background:var(--bg);scroll-behavior:smooth}
body{margin:0;background:radial-gradient(1000px 520px at 80% -12%,rgba(63,101,171,.18),transparent 65%),var(--bg);color:var(--text);font:15px/1.48 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
button,input,select{font:inherit}
button{touch-action:manipulation}
.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px clamp(14px,3vw,42px);background:rgba(9,13,22,.91);backdrop-filter:blur(16px);border-bottom:1px solid rgba(126,153,194,.16)}
.brand{display:flex;align-items:center;gap:12px}.brand-mark{width:39px;height:39px;display:grid;place-items:center;border-radius:12px;background:linear-gradient(135deg,#1c4166,#18233b);border:1px solid #31577f;color:#a6d1ff;font-weight:900;font-size:19px}.brand-title{font-size:13px;font-weight:900;letter-spacing:.13em}.brand-sub{font-size:12px;color:var(--muted);margin-top:2px}
.top-actions{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap}.live-badge,.paper-badge,.tag{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:#111a29;color:#b8c7dd;border-radius:999px;padding:6px 10px;font-size:11px;font-weight:800;max-width:100%}.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px rgba(91,212,160,.13)}.paper-badge{color:#8fe0c0;border-color:#245c4a;background:#10271f}.backlink{font-size:13px;color:var(--muted);white-space:nowrap}
main{width:min(1600px,100%);margin:0 auto;padding:clamp(14px,2.4vw,34px) clamp(12px,2.5vw,36px) 52px}
.hero{display:flex;align-items:flex-start;justify-content:space-between;gap:22px;margin:8px 0 18px;flex-wrap:wrap}.hero-copy{flex:1 1 460px}.eyebrow{font-size:11px;letter-spacing:.16em;color:var(--cyan);font-weight:900}.hero h1{font-size:clamp(28px,3.8vw,44px);letter-spacing:-.035em;line-height:1.08;margin:8px 0 12px}.hero p{max-width:870px;margin:0;color:var(--muted);font-size:14px}.hero-side{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.callout{border:1px solid rgba(241,197,110,.28);background:linear-gradient(120deg,rgba(75,54,20,.42),rgba(40,32,21,.3));color:#f2dfb3;border-radius:13px;padding:12px 15px;margin:15px 0 20px;font-size:12px}.callout strong{color:#ffe7a8}.callout a{color:#ffd88b;text-decoration:underline}
.panel{border:1px solid var(--line);background:linear-gradient(150deg,rgba(19,29,45,.97),rgba(14,21,33,.98));border-radius:18px;box-shadow:var(--shadow);padding:clamp(14px,1.8vw,23px);margin:18px 0;min-width:0}
.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:15px}.section-title{margin:0;font-size:clamp(18px,2vw,22px);font-weight:850;letter-spacing:-.02em}.section-sub{font-size:12px;color:var(--muted);margin:5px 0 0;max-width:870px}.section-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.kpi-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:16px 0}
.kpi{border:1px solid var(--line);border-radius:13px;padding:13px;background:linear-gradient(145deg,#151f30,#101725);min-width:0}.kpi-label{font-size:11px;color:var(--muted);line-height:1.35}.kpi-value{font-weight:900;font-size:clamp(17px,1.9vw,25px);letter-spacing:-.035em;line-height:1.22;margin-top:8px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.kpi-note{font-size:10px;color:var(--subtle);margin-top:6px;overflow-wrap:anywhere}.positive{color:var(--green)!important}.negative{color:var(--red)!important}.warn{color:var(--amber)!important}.muted{color:var(--muted)!important}
.position-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.position-card{border:1px solid #2b3b54;background:linear-gradient(155deg,#172338,#101826 76%);border-radius:16px;padding:16px;min-width:0;overflow:hidden}.pos-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}.pos-name{display:flex;flex-direction:column;gap:4px}.pos-pair{font-size:20px;font-weight:900;letter-spacing:-.025em}.pos-direction{font-size:11px;color:var(--muted)}.pos-state{font-size:10px;font-weight:900;color:#82dfb7;border:1px solid #29664f;background:#102b22;padding:5px 8px;border-radius:999px;white-space:nowrap}
.pos-principal{margin:16px 0 13px;display:grid;grid-template-columns:1fr 1fr;gap:10px}.principal-box{border-radius:12px;background:rgba(5,10,19,.35);border:1px solid rgba(119,145,181,.13);padding:11px}.principal-box span{display:block;color:var(--muted);font-size:10px}.principal-box strong{display:block;margin-top:5px;font-size:clamp(17px,2vw,23px);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.price-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:12px 0;border-top:1px solid rgba(125,149,183,.16);border-bottom:1px solid rgba(125,149,183,.16)}.data-point{min-width:0}.data-label{font-size:10px;color:var(--muted);display:block}.data-value{display:block;font-size:13px;font-weight:800;margin-top:4px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.pos-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:13px 0}.detail-line{display:flex;flex-direction:column;gap:3px}.detail-line span{font-size:10px;color:var(--muted)}.detail-line b{font-size:12px;overflow-wrap:anywhere}.gap-track{height:6px;background:#26364c;border-radius:999px;overflow:hidden;margin:8px 0 5px}.gap-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#58d5bc,#83b7ff)}.mini-label{font-size:10px;color:var(--muted);display:flex;justify-content:space-between;gap:8px}.spark{display:block;width:100%;height:34px;margin-top:8px}.position-footer{font-size:10px;line-height:1.45;color:var(--muted);border-top:1px solid rgba(125,149,183,.16);padding-top:10px;margin-top:10px}.position-footer strong{color:#d4e2f8}
.empty-state{border:1px dashed #3a4c66;border-radius:14px;padding:26px 16px;text-align:center;color:var(--muted);background:rgba(8,14,24,.36)}.empty-state strong{display:block;color:var(--text);font-size:15px;margin-bottom:6px}.empty-state p{font-size:12px;margin:0}
.controls{display:grid;grid-template-columns:repeat(5,minmax(0,1fr)) auto;gap:10px;align-items:end}.field{min-width:0}.field label{display:block;color:var(--muted);font-size:11px;margin-bottom:6px}.field input,.field select{width:100%;min-width:0;background:#0a111d;border:1px solid #30415a;border-radius:10px;color:var(--text);padding:10px 11px;outline:none}.field input:focus,.field select:focus{border-color:#74adf6;box-shadow:0 0 0 3px rgba(116,173,246,.13)}.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:10px;border:1px solid #477cba;background:linear-gradient(180deg,#2c5b8f,#21466f);color:#f1f7ff;padding:10px 14px;font-size:12px;font-weight:900;cursor:pointer;white-space:nowrap;min-height:40px}.btn:hover{filter:brightness(1.1)}.btn:disabled{opacity:.55;cursor:wait}.btn.secondary{background:#172235;border-color:#354862;color:#d9e5f7}.btn.slim{min-height:32px;padding:7px 10px}
.statusline{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:11px;color:var(--muted);font-size:11px}.status-text{overflow-wrap:anywhere}.market-strip{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.market-chip{padding:7px 10px;border:1px solid var(--line);border-radius:10px;background:#0d1522;font-size:11px;color:var(--muted)}.market-chip b{color:var(--text);font-variant-numeric:tabular-nums}
.offer-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.offer-card{border:1px solid #2b3a51;border-radius:14px;padding:14px;background:rgba(9,15,25,.38);min-width:0;overflow:hidden}.offer-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap}.offer-pair{font-size:16px;font-weight:900}.offer-meta{font-size:11px;color:var(--muted);margin-top:3px}.tag.good{color:var(--green);border-color:#2e654e;background:#11271f}.tag.bad{color:var(--red);border-color:#733843;background:#2c171e}.tag.warn{color:var(--amber);border-color:#68512c;background:#2a2114}.offer-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:13px 0}.offer-metric{min-width:0}.offer-metric span{font-size:10px;color:var(--muted);display:block}.offer-metric b{display:block;font-size:13px;margin-top:3px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.offer-reason{border-top:1px solid rgba(125,149,183,.15);padding-top:9px;color:var(--muted);font-size:11px;line-height:1.45;overflow-wrap:anywhere}.offer-reason strong{color:var(--text)}
.history-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.history-card{padding:12px;border:1px solid var(--line);background:rgba(9,15,25,.38);border-radius:12px;min-width:0}.history-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;flex-wrap:wrap}.history-name{font-weight:850}.history-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:10px}.history-detail span{display:block;font-size:10px;color:var(--muted)}.history-detail b{display:block;margin-top:3px;font-size:12px;overflow-wrap:anywhere}
.tax-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.tax-card{border:1px solid var(--line);background:#101927;border-radius:12px;padding:13px}.tax-card h3{font-size:13px;margin:0 0 6px}.tax-card p{font-size:11px;color:var(--muted);margin:0;line-height:1.5}.smallprint{font-size:11px;color:var(--muted);line-height:1.55}.divider{height:1px;background:var(--line);margin:14px 0}
.footer{padding:20px 2px 0;color:var(--subtle);font-size:10px;line-height:1.6}
@media(max-width:1120px){.kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.controls{grid-template-columns:repeat(3,minmax(0,1fr))}.controls .btn{width:100%}}
@media(max-width:760px){.topbar{position:static;align-items:flex-start}.top-actions{gap:6px}.backlink{font-size:11px}.hero{margin-top:5px}.position-grid,.offer-grid,.history-grid{grid-template-columns:minmax(0,1fr)}.tax-grid{grid-template-columns:minmax(0,1fr)}.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.controls{grid-template-columns:repeat(2,minmax(0,1fr))}.controls .field:last-of-type{grid-column:auto}.position-card{padding:13px}.pos-pair{font-size:18px}.price-row{gap:5px}.data-value{font-size:12px}}
@media(max-width:430px){main{padding:12px 10px 30px}.topbar{padding:12px 10px}.brand-sub{font-size:10px}.top-actions{width:100%;justify-content:space-between}.hero h1{font-size:29px}.panel{padding:12px;border-radius:14px;margin:13px 0}.kpi-grid{gap:7px}.kpi{padding:10px}.kpi-value{font-size:18px}.controls{grid-template-columns:minmax(0,1fr)}.controls .btn{width:100%}.pos-principal{gap:7px}.principal-box{padding:9px}.principal-box strong{font-size:18px}.price-row{grid-template-columns:repeat(3,minmax(0,1fr))}.offer-metrics{gap:6px}.offer-metric b{font-size:12px}}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand"><div class="brand-mark">◈</div><div><div class="brand-title">BI / BINANCE INTEL</div><div class="brand-sub">Dual Investment · live paper monitor</div></div></div>
  <div class="top-actions"><span class="live-badge"><i class="live-dot"></i><span id="di-live-status">Connecting live prices…</span></span><span class="paper-badge">PAPER ONLY · NO ORDERS</span><a class="backlink" href="/">← Workspace</a></div>
</header>
<main>
  <section class="hero">
    <div class="hero-copy"><div class="eyebrow">STRUCTURED-YIELD RESEARCH · 7-DAY MAX</div><h1>Dual Investment Lab</h1><p>See your paper positions first: principal committed, live underlying price, current settlement-scenario value, potential gain or loss, reward estimate, and time left. The scanner reads live Binance product offers but never subscribes or moves funds.</p></div>
    <div class="hero-side"><span class="tag">Auto-scan · 5 min</span><span class="tag good">Max lock-up · 7 days</span></div>
  </section>
  <div class="callout"><strong>Important distinction:</strong> these are simulated positions. The live value shown is a <strong>scenario estimate if the product settled at the current underlying price</strong>, not Binance's official mark-to-market price. Real Dual Investment subscriptions cannot normally be cancelled or redeemed early. Reward, settlement and tax estimates are not guarantees.</div>

  <section class="panel" id="positions-panel">
    <div class="section-head"><div><h2 class="section-title">Open paper positions</h2><p class="section-sub">Highest priority · live prices refresh every 10 seconds. Position marks are also stored in PostgreSQL at five-minute intervals for review.</p></div><div class="section-actions"><span class="tag" id="di-position-count">0 open positions</span><button class="btn secondary slim" id="di-refresh">↻ Refresh now</button></div></div>
    <div class="kpi-grid" id="di-kpis">
      <div class="kpi"><div class="kpi-label">Principal committed</div><div class="kpi-value" id="di-invested">—</div><div class="kpi-note">Total open paper principal</div></div>
      <div class="kpi"><div class="kpi-label">Live scenario value</div><div class="kpi-value" id="di-current-value">—</div><div class="kpi-note">Not an early-redemption quote</div></div>
      <div class="kpi"><div class="kpi-label">Estimated open PnL</div><div class="kpi-value" id="di-open-pnl">—</div><div class="kpi-note">Scenario PnL vs paper principal</div></div>
      <div class="kpi"><div class="kpi-label">Reward estimate at settlement</div><div class="kpi-value" id="di-reward">—</div><div class="kpi-note">APR × period estimate</div></div>
      <div class="kpi"><div class="kpi-label">Open-position tax reserve</div><div class="kpi-value" id="di-open-tax">Not assessed</div><div class="kpi-note">No tax charged in paper mode</div></div>
    </div>
    <div id="di-open-positions" class="position-grid"><div class="empty-state"><strong>Loading open paper positions…</strong><p>Requesting the saved ledger and live Binance prices.</p></div></div>
    <div class="statusline"><span class="status-text" id="di-mark-status">Waiting for first live mark.</span><span id="di-last-updated" class="muted"></span></div>
  </section>

  <section class="panel" id="scanner-panel">
    <div class="section-head"><div><h2 class="section-title">Scanner settings</h2><p class="section-sub">Your total paper budget is shared across newly selected positions. A full budget is not silently committed again on every five-minute scan.</p></div><span class="tag good">Default maximum 7 days</span></div>
    <div class="controls">
      <div class="field"><label for="di-amount">Total paper budget (USDT)</label><input id="di-amount" type="number" min="1" max="100000" step="10" value="150"></div>
      <div class="field"><label for="di-direction">Direction</label><select id="di-direction"><option value="both">Buy Low + Sell High</option><option value="buy_low">Buy Low only</option><option value="sell_high">Sell High only</option></select></div>
      <div class="field"><label for="di-distance">Maximum target gap (%)</label><input id="di-distance" type="number" min="0.1" max="25" step="0.1" value="5"></div>
      <div class="field"><label for="di-duration">Maximum settlement time</label><select id="di-duration"><option value="8">8 hours</option><option value="24">24 hours</option><option value="48">48 hours</option><option value="168" selected>7 days (default)</option><option value="0">All durations</option></select></div>
      <div class="field"><label for="di-tail">Maximum P01/P05 loss (%)</label><input id="di-tail" type="number" min="0.1" max="20" step="0.1" value="3"></div>
      <button class="btn" id="di-scan">Scan live offers</button>
    </div>
    <div class="statusline"><span class="status-text" id="di-status">Loading recorded scans…</span><span class="muted" id="di-scan-clock">Last scan: —</span></div>
    <div class="market-strip" id="di-market-chips"></div>
  </section>

  <section class="panel">
    <div class="section-head"><div><h2 class="section-title">Best offers found</h2><p class="section-sub">Only offers within your selected settlement horizon are eligible. A zero-offer shortlist is valid when no product passes every gate.</p></div><span class="tag" id="di-offer-source">Waiting for live scan</span></div>
    <div id="di-offer-grid" class="offer-grid"><div class="empty-state"><strong>Scanning Binance offers…</strong><p>Offer cards will appear here after the first live scan.</p></div></div>
  </section>

  <section class="panel">
    <div class="section-head"><div><h2 class="section-title">Settlement, loss & tax ledger</h2><p class="section-sub">Every paper decision is preserved, including archived legacy records and settled proxy results. Negative outcomes are shown as losses, not hidden.</p></div></div>
    <div class="kpi-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="kpi"><div class="kpi-label">Settled paper PnL</div><div class="kpi-value" id="di-settled-pnl">—</div><div class="kpi-note">Before illustrative tax reserve</div></div>
      <div class="kpi"><div class="kpi-label">Illustrative tax reserve</div><div class="kpi-value" id="di-settled-tax">—</div><div class="kpi-note">Only positive settled proxy PnL</div></div>
      <div class="kpi"><div class="kpi-label">Settled PnL after reserve</div><div class="kpi-value" id="di-after-tax">—</div><div class="kpi-note">Indicative, not a filed tax calculation</div></div>
    </div>
    <div class="history-grid" id="di-ledger"><div class="empty-state"><strong>Loading ledger…</strong><p>Settled and archived paper records will be listed here.</p></div></div>
  </section>

  <section class="panel">
    <div class="section-head"><div><h2 class="section-title">Tax & risk, plainly stated</h2><p class="section-sub">No tax is deducted and no real asset transfer happens in this paper-only test.</p></div></div>
    <div class="tax-grid">
      <article class="tax-card"><h3>Potential India VDA tax</h3><p>The ledger shows an illustrative 30% base-rate reserve only on positive settled paper PnL, and only as a scenario where the income qualifies under the VDA-transfer tax regime. Surcharge, cess and individual circumstances are excluded. Actual treatment of Dual Investment rewards and conversion events is not determined by this app.</p></article>
      <article class="tax-card"><h3>Losses & tax set-off</h3><p>If VDA-transfer rules apply, section 115BBH says losses from transfer of a VDA cannot be set off against other income or carried forward. A negative open scenario does not become a tax credit here. No tax reserve is calculated against a paper loss.</p></article>
      <article class="tax-card"><h3>TDS & settlement</h3><p>TDS is not automatically deducted from simulated PnL. Whether section 194S or another rule applies to a particular Dual Investment transaction depends on its legal character and facts. Confirm the actual treatment with an Indian tax professional before subscribing.</p></article>
    </div>
    <div class="divider"></div>
    <p class="smallprint"><strong>What the live mark means:</strong> the app estimates what each paper position's outcome could look like if the product fixed at the current spot price. It is not the product's market resale price. Binance describes Dual Investment as a non-principal-protected structured product; target-price conversion can change the asset you receive and its value can fall. The official fixing price is based on a prescribed pre-settlement time window, not the latest ticker.</p>
  </section>

  <section class="panel">
    <div class="section-head"><div><h2 class="section-title">Scan & data-quality history</h2><p class="section-sub">Shows the recent live API scans, data errors, configured horizon, and number of candidates selected. Failed requests are reported, not replaced by mock data.</p></div></div>
    <div id="di-scan-history" class="history-grid"><div class="empty-state"><strong>Loading scan history…</strong><p>Recorded API scans will appear here.</p></div></div>
  </section>
  <footer class="footer">Sources: Binance Dual Investment product-list endpoint and Binance Spot market-data endpoint. All position valuations, settlement prices and tax amounts displayed on this page are paper estimates. No real subscription or transfer capability is present on this page.</footer>
</main>
<script>
(function(){
"use strict";
var $=function(id){return document.getElementById(id)};
var lastState=null, refreshing=false, lastLivePrices={};
function esc(v){return String(v===null||v===undefined?"—":v).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function number(v,d){if(v===null||v===undefined||v==="")return "—";var n=Number(v);if(!Number.isFinite(n))return "—";return n.toLocaleString("en-US",{minimumFractionDigits:d===undefined?2:d,maximumFractionDigits:d===undefined?2:d})}
function usdt(v){if(v===null||v===undefined||v==="")return "—";var n=Number(v);if(!Number.isFinite(n))return "—";return (n<0?"−":"")+Math.abs(n).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:4})+" USDT"}
function signed(v){if(v===null||v===undefined||v==="")return "—";var n=Number(v);if(!Number.isFinite(n))return "—";return (n>0?"+":n<0?"−":"")+Math.abs(n).toFixed(2)+"%"}
function pct(v,d){return v===null||v===undefined?"—":number(Number(v)*100,d===undefined?1:d)+"%"}
function colorClass(v){var n=Number(v);return !Number.isFinite(n)?"":n>0?"positive":n<0?"negative":""}
function dt(iso){if(!iso)return "—";var x=new Date(iso);return Number.isNaN(x.getTime())?String(iso):x.toLocaleString("en-GB",{timeZone:"UTC",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit",hour12:false})+" UTC"}
function duration(hours){if(hours===null||hours===undefined)return "—";var h=Math.max(0,Number(hours));if(!Number.isFinite(h))return "—";if(h<24)return number(h,1)+" hours";var d=h/24;return number(d,d<10?1:0)+" days"}
function countdown(ms){var diff=Number(ms)-Date.now();if(!Number.isFinite(diff)||diff<=0)return "Settling / maturity passed";var s=Math.floor(diff/1000),d=Math.floor(s/86400);s%=86400;var h=Math.floor(s/3600);s%=3600;var m=Math.floor(s/60);if(d>0)return d+"d "+h+"h "+m+"m";if(h>0)return h+"h "+m+"m";return m+"m"}
function positionIsOpen(p){return String(p.status||"").toUpperCase()==="OPEN"}
function openPositions(state){return (state.paper||[]).filter(positionIsOpen)}
function newestFirst(a,b){return String(b.created_at_utc||"").localeCompare(String(a.created_at_utc||""))}
async function request(url,options){var res=await fetch(url,options||{});var data=await res.json().catch(function(){return {error:"Server returned an unreadable response"}});if(!res.ok||data.error)throw new Error(data.error||("HTTP "+res.status));return data}
function sparkline(history){if(!Array.isArray(history)||history.length<2)return '<div class="position-footer">Trend history is building. A new mark is recorded at five-minute intervals.</div>';var rows=history.slice().sort(function(a,b){return String(a.observed_at_utc).localeCompare(String(b.observed_at_utc))});var vals=rows.map(function(x){return Number(x.unrealized_pnl_usdt)}).filter(Number.isFinite);if(vals.length<2)return "";var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals);var span=hi-lo||1;var pts=vals.map(function(v,i){return (i/(vals.length-1)*300).toFixed(1)+","+((29-(v-lo)/span*24)).toFixed(1)}).join(" ");var col=vals[vals.length-1]>=0?"#5bd4a0":"#ff8e98";return '<svg class="spark" viewBox="0 0 300 34" preserveAspectRatio="none" role="img" aria-label="Recent estimated PnL history"><line x1="0" y1="31" x2="300" y2="31" stroke="#2a3a51" stroke-width="1"/><polyline points="'+pts+'" fill="none" stroke="'+col+'" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'}
function positionCard(p){
 var pnl=p.unrealized_pnl_usdt, gap=Math.max(0,Number(p.target_gap_pct||0)), progress=Math.max(0,Math.min(100,100-gap/Math.max(Number(p.target_distance_at_entry_pct)||5,0.1)*100));
 var activeReached=String(p.scenario_state||"").indexOf("TRIGGERED")>=0;
 var scenarioTag=activeReached?'<span class="tag warn">Target condition currently met</span>':'<span class="tag">Target condition not met</span>';
 var move=p.entry_spot>0&&p.current_spot>0?(p.current_spot/p.entry_spot-1)*100:null;
 var unitLine=p.deposit_units===null||p.deposit_units===undefined?"":'<div class="detail-line"><span>Paper subscription amount</span><b>'+number(p.deposit_units,8)+' '+esc(p.deposit_currency||"")+'</b></div>';
 var rewardProjected=p.estimated_reward_usdt;
 return '<article class="position-card">'+
 '<div class="pos-top"><div class="pos-name"><div class="pos-pair">'+esc(p.pair)+'</div><div class="pos-direction">'+esc(p.direction==="BUY_LOW"?"BUY LOW · deposit stablecoin":"SELL HIGH · deposit underlying asset")+'</div></div><span class="pos-state">OPEN PAPER POSITION</span></div>'+
 '<div class="pos-principal"><div class="principal-box"><span>Principal invested</span><strong>'+usdt(p.amount_usdt)+'</strong></div><div class="principal-box"><span>Scenario value at live price</span><strong>'+usdt(p.current_value_usdt)+'</strong><div class="'+colorClass(pnl)+'" style="font-size:11px;font-weight:850;margin-top:4px">'+usdt(pnl)+' estimated PnL</div></div></div>'+
 '<div class="price-row"><div class="data-point"><span class="data-label">Live spot</span><span class="data-value">'+number(p.current_spot,Number(p.current_spot)>100?2:4)+'</span></div><div class="data-point"><span class="data-label">Move since entry</span><span class="data-value '+colorClass(move)+'">'+signed(move)+'</span></div><div class="data-point"><span class="data-label">Target price</span><span class="data-value">'+number(p.target_price,Number(p.target_price)>100?2:4)+'</span></div></div>'+
 '<div style="margin:12px 0 4px">'+scenarioTag+' <span class="tag">Gap '+number(p.target_gap_pct,2)+'%</span></div><div class="gap-track"><div class="gap-fill" style="width:'+progress+'%"></div></div><div class="mini-label"><span>Target proximity (indicative)</span><span>'+number(p.target_gap_pct,2)+'% away</span></div>'+
 '<div class="pos-details">'+
 '<div class="detail-line"><span>Time remaining</span><b class="warn">'+countdown(p.settle_date_ms)+'</b></div>'+
 '<div class="detail-line"><span>Settlement date</span><b>'+dt(p.settled_at_utc||new Date(Number(p.settle_date_ms)).toISOString())+'</b></div>'+
 '<div class="detail-line"><span>Locked APR</span><b>'+number(Number(p.apr_rate)*100,2)+'% APR</b></div>'+
 '<div class="detail-line"><span>Projected reward at maturity</span><b>'+usdt(rewardProjected)+'</b></div>'+
 '<div class="detail-line"><span>Accrued reward proxy so far</span><b>'+usdt(p.accrued_reward_usdt)+'</b></div>'+
 '<div class="detail-line"><span>Tax reserve while open</span><b>Not assessed</b></div>'+
 unitLine+
 '<div class="detail-line"><span>Worst-tail historical P05 estimate</span><b class="'+colorClass(p.p05_pnl_usdt)+'">'+usdt(p.p05_pnl_usdt)+'</b></div>'+
 '</div>'+sparkline(p.mark_history||[])+
 '<div class="position-footer"><strong>Scenario valuation only.</strong> Price source updated '+esc(dt(p.live_price_updated_at))+'. '+esc(p.mark_method||"The app cannot redeem a Dual Investment subscription early.")+' '+esc(p.live_price_error||"")+'</div>'+
 '</article>'
}
function empty(title,body){return '<div class="empty-state"><strong>'+esc(title)+'</strong><p>'+esc(body)+'</p></div>'}
function drawOpen(state){
 var pos=openPositions(state).sort(newestFirst), stats=state.stats||{};
 $("di-position-count").textContent=pos.length+" open position"+(pos.length===1?"":"s");
 $("di-invested").textContent=usdt(stats.invested_open_usdt||0);
 $("di-current-value").textContent=usdt(stats.current_value_open_usdt||0);
 $("di-open-pnl").textContent=usdt(stats.unrealized_pnl_open_usdt||0);
 $("di-open-pnl").className="kpi-value "+colorClass(stats.unrealized_pnl_open_usdt||0);
 $("di-reward").textContent=usdt(stats.projected_reward_open_usdt||0);
 $("di-open-tax").textContent="Not assessed";
 $("di-open-positions").innerHTML=pos.length?pos.map(positionCard).join(""):empty("No open positions right now","The ledger is intact. The scanner will only start a new paper position when an eligible offer passes the gates and the total paper budget allows it.");
 var mark=state.live_status||{};
 $("di-mark-status").textContent=mark.status==="LIVE"?"Prices refreshed from Binance Spot API · "+(mark.symbols_updated||0)+" symbols":(mark.message||"Live market mark unavailable; last stored values are retained.");
 $("di-last-updated").textContent="Last mark: "+dt(mark.updated_at_utc||"");
 $("di-live-status").textContent=mark.status==="LIVE"?"Live prices · "+dt(mark.updated_at_utc):"Prices temporarily stale";
}
function drawMarkets(markets){var host=$("di-market-chips"),entries=Object.keys(markets||{}).filter(function(k){return markets[k]&&markets[k].spot});host.innerHTML=entries.map(function(k){var m=markets[k];return '<span class="market-chip"><b>'+esc(k)+'</b> '+number(m.spot,Number(m.spot)>100?2:4)+' · 24h '+signed(m.trend_24h_pct)+' · vol '+number(m.volatility_24h_pct,2)+'%</span>'}).join("")}
function offerCard(r,i){
 var selected=!!r.selected,decision=String(r.decision||"UNKNOWN"),isBad=decision==="REJECTED"||decision==="EXPIRED"||decision==="CAPITAL_BUDGET_FULL";
 var cls=selected?"good":isBad?"bad":"warn";
 var reasons=Array.isArray(r.reasons)?r.reasons:[];
 var targetUnit=r.direction==="BUY_LOW"?"quote target":"target";
 var usdEdge=r.expected_edge_vs_hold_usdt;
 return '<article class="offer-card"><div class="offer-head"><div><div class="offer-pair">'+esc(r.pair)+' · '+esc(r.direction==="BUY_LOW"?"Buy Low":"Sell High")+'</div><div class="offer-meta">Settlement '+dt(new Date(Number(r.settle_date_ms)).toISOString())+' · '+duration(r.hours_to_settle)+' left</div></div><span class="tag '+cls+'">'+esc(selected?"PAPER ACTIVE / SELECTED":decision.replace(/_/g," "))+'</span></div>'+
 '<div class="offer-metrics">'+
 '<div class="offer-metric"><span>APR</span><b>'+number(Number(r.apr_rate)*100,2)+'%</b></div>'+
 '<div class="offer-metric"><span>Target · '+targetUnit+'</span><b>'+number(r.target_price,Number(r.target_price)>100?2:4)+'</b></div>'+
 '<div class="offer-metric"><span>Live spot</span><b>'+number(r.spot_price,Number(r.spot_price)>100?2:4)+'</b></div>'+
 '<div class="offer-metric"><span>Target gap</span><b>'+number(r.target_distance_pct,2)+'%</b></div>'+
 '<div class="offer-metric"><span>Reward estimate</span><b>'+usdt(r.estimated_reward_usdt)+'</b></div>'+
 '<div class="offer-metric"><span>Expected edge vs benchmark</span><b class="'+colorClass(usdEdge)+'">'+usdt(usdEdge)+'</b></div>'+
 '<div class="offer-metric"><span>Expected scenario PnL</span><b class="'+colorClass(r.expected_pnl_usdt)+'">'+usdt(r.expected_pnl_usdt)+'</b></div>'+
 '<div class="offer-metric"><span>P05 simulated PnL</span><b class="'+colorClass(r.p05_pnl_usdt)+'">'+usdt(r.p05_pnl_usdt)+'</b></div>'+
 '<div class="offer-metric"><span>Historical windows</span><b>'+number(r.history_sample_count,0)+'</b></div></div>'+
 '<div class="offer-reason"><strong>Gate explanation:</strong> '+esc(reasons.join("; ")||"Passed the configured gates; ranking chooses the best offer per underlying asset.")+'</div></article>'
}
function drawOffers(state){
 var rows=(state.offers||[]).slice();
 rows.sort(function(a,b){if(!!a.selected!==!!b.selected)return a.selected?-1:1;return Number(b.score||-999)-Number(a.score||-999)});
 $("di-offer-source").textContent=state.latest_scan?"Live API scan · "+number(state.latest_scan.offers_recorded,0)+" evaluated":"Waiting for a live scan";
 $("di-offer-grid").innerHTML=rows.length?rows.slice(0,100).map(offerCard).join(""):empty("No eligible offers returned","There may still be rejected offers in the database. Expand the recorded scan details below to see the filters and API diagnostics.");
}
function drawLedger(state){
 var stats=state.stats||{};
 $("di-settled-pnl").textContent=usdt(stats.settled_pnl_usdt||0);
 $("di-settled-pnl").className="kpi-value "+colorClass(stats.settled_pnl_usdt||0);
 $("di-settled-tax").textContent=usdt(stats.estimated_settled_tax_usdt||0);
 $("di-after-tax").textContent=usdt(stats.settled_after_tax_pnl_usdt||0);
 $("di-after-tax").className="kpi-value "+colorClass(stats.settled_after_tax_pnl_usdt||0);
 var rows=(state.paper||[]).filter(function(p){return !positionIsOpen(p)}).sort(newestFirst);
 $("di-ledger").innerHTML=rows.length?rows.slice(0,80).map(function(p){
  var status=String(p.status||"UNKNOWN"),tag=status==="SETTLED_PROXY"?"good":status==="CLOSED_POLICY"?"warn":"";
  var pnl=p.paper_pnl_usdt, tax=p.estimated_tax_usdt;
  return '<article class="history-card"><div class="history-top"><div><div class="history-name">'+esc(p.pair)+' · '+esc(p.direction==="BUY_LOW"?"Buy Low":"Sell High")+'</div><div class="offer-meta">Started '+dt(p.created_at_utc)+'</div></div><span class="tag '+tag+'">'+esc(status.replace(/_/g," "))+'</span></div><div class="history-details">'+
  '<div class="history-detail"><span>Paper principal</span><b>'+usdt(p.amount_usdt)+'</b></div>'+
  '<div class="history-detail"><span>Target / entry</span><b>'+number(p.target_price,Number(p.target_price)>100?2:4)+' / '+number(p.entry_spot,Number(p.entry_spot)>100?2:4)+'</b></div>'+
  '<div class="history-detail"><span>Settled proxy PnL</span><b class="'+colorClass(pnl)+'">'+usdt(pnl)+'</b></div>'+
  '<div class="history-detail"><span>Illustrative tax reserve</span><b>'+usdt(tax)+'</b></div>'+
  '<div class="history-detail"><span>After-reserve scenario</span><b class="'+colorClass(pnl===null||pnl===undefined?null:Number(pnl)-Number(tax||0))+'">'+(pnl===null||pnl===undefined?"Not settled":usdt(Number(pnl)-Number(tax||0)))+'</b></div>'+
  '<div class="history-detail"><span>Fixing price proxy</span><b>'+number(p.fixing_price_proxy,Number(p.fixing_price_proxy)>100?2:4)+'</b></div>'+
  '</div><div class="position-footer">'+esc(p.settlement_note||p.tax_note||"No tax is deducted. This is a simulated ledger entry only.")+'</div></article>'
 }).join(""):empty("No settled or archived records yet","As paper positions mature or are archived by the seven-day policy, their PnL and tax notes will be recorded here.");
}
function drawScanHistory(state){
 var rows=state.scans||[];
 $("di-scan-history").innerHTML=rows.length?rows.slice(0,15).map(function(r){
  var markets=r.markets||{},cfg=markets.scan_config||{},errs=Array.isArray(r.errors)?r.errors:[];
  var horizon=cfg.max_settlement_hours===0?"All":cfg.max_settlement_hours===undefined?"—":duration(cfg.max_settlement_hours);
  return '<article class="history-card"><div class="history-top"><div><div class="history-name">'+dt(r.started_at_utc)+'</div><div class="offer-meta">Scan ID '+esc(String(r.scan_id||"").slice(0,8))+'</div></div><span class="tag '+(r.status==="OK"?"good":"warn")+'">'+esc(r.status||"UNKNOWN")+'</span></div><div class="history-details">'+
  '<div class="history-detail"><span>Offers evaluated</span><b>'+number(r.offers_recorded,0)+'</b></div>'+
  '<div class="history-detail"><span>Selected</span><b>'+number(r.selected_count,0)+'</b></div>'+
  '<div class="history-detail"><span>Max settlement horizon</span><b>'+esc(horizon)+'</b></div>'+
  '<div class="history-detail"><span>Paper notional budget</span><b>'+usdt(cfg.amount_usdt)+'</b></div>'+
  '<div class="history-detail"><span>Markets with live prices</span><b>'+number(Object.keys(markets).filter(function(k){return markets[k]&&markets[k].spot}).length,0)+'</b></div>'+
  '<div class="history-detail"><span>API diagnostics</span><b class="'+(errs.length?"warn":"positive")+'">'+number(errs.length,0)+'</b></div>'+
  '</div>'+(errs.length?'<div class="position-footer">'+esc(errs.join(" · "))+'</div>':'')+'</article>'
 }).join(""):empty("No scans recorded","A scan result will appear after the background scanner completes its first run.");
}
function render(state){
 lastState=state;
 drawOpen(state);
 drawMarkets(state.latest_scan&&state.latest_scan.markets?state.latest_scan.markets:{});
 drawOffers(state);
 drawLedger(state);
 drawScanHistory(state);
 var scan=state.latest_scan;
 $("di-scan-clock").textContent="Last scan: "+(scan?dt(scan.started_at_utc):"—");
 if(scan&&scan.errors&&scan.errors.length){$("di-status").textContent="Last scan "+scan.status+" · "+scan.errors.length+" diagnostics recorded; see history below."}
 else if(scan){$("di-status").textContent="Last scan "+scan.status+" · "+number(scan.offers_recorded,0)+" offers reviewed · no real subscription is possible."}
 else{$("di-status").textContent="No scan recorded yet; waiting for the first live API scan."}
}
async function loadState(){
 if(refreshing)return;refreshing=true;
 try{var state=await request("/api/dual-investment/state");render(state);if(!state.latest_scan)scanNow(true)}
 catch(e){$("di-live-status").textContent="Price/data connection issue";$("di-mark-status").textContent="Could not refresh: "+e.message}
 finally{refreshing=false}
}
async function scanNow(silent){
 var button=$("di-scan");if(button.disabled)return;button.disabled=true;var old=button.textContent;button.textContent="Requesting Binance…";
 if(!silent)$("di-status").textContent="Requesting current Binance product offers and candle history…";
 var payload={amount_usdt:Number($("di-amount").value||150),direction_filter:$("di-direction").value,max_target_distance_pct:Number($("di-distance").value||5),max_tail_loss_pct:Number($("di-tail").value||3),max_settlement_hours:Number($("di-duration").value||168)};
 try{var result=await request("/api/dual-investment/scan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});var state=await request("/api/dual-investment/state");render(state);$("di-status").textContent="Scan recorded · "+number(result.products_fetched,0)+" offers evaluated · "+number(result.selected_count,0)+" selected · "+((result.errors||[]).length)+" diagnostics."}
 catch(e){$("di-status").textContent="Scan failed: "+e.message+". No sample or mock offers were inserted."}
 finally{button.disabled=false;button.textContent=old}
}
$("di-scan").addEventListener("click",function(){scanNow(false)});
$("di-refresh").addEventListener("click",function(){loadState()});
loadState();
setInterval(loadState,10000);
})();
</script>
</body>
</html>"""

if "BINANCE_DUAL_INVESTMENT_LIVE_PAPER_MONITOR_V2" not in source:
    page_pat = re.compile(r'_DI_PAGE = r""".*?"""\n\n\n@app\.get\("/dual-investment"\)', re.S)
    new_page = '_DI_PAGE = r"""' + _PAGE + '"""\n\n\n@app.get("/dual-investment")'
    source, page_count = page_pat.subn(lambda m: new_page, source, count=1)
    if page_count != 1:
        raise RuntimeError("Could not replace the existing Dual Investment page template")

    # Seven-day is the default everywhere; longer terms are not scanned unless explicitly requested.
    replacements = [
        ("def _di_scan(amount_usdt, direction_filter, max_distance, max_tail_loss_pct, max_settlement_hours=24):",
         "def _di_scan(amount_usdt, direction_filter, max_distance, max_tail_loss_pct, max_settlement_hours=168):"),
        ("_di_f(max_settlement_hours, 24.0)", "_di_f(max_settlement_hours, 168.0)"),
        ('args.get("max_settlement_hours", 24)', 'args.get("max_settlement_hours", 168)'),
        ('_di_bg_os.environ.get("DI_MAX_SETTLEMENT_HOURS", "24")', '_di_bg_os.environ.get("DI_MAX_SETTLEMENT_HOURS", "168")'),
    ]
    for old, new in replacements:
        source = source.replace(old, new)

    # Archive out-of-policy legacy paper records, preserving the full history and explaining why.
    archive_anchor = '    if direction_filter not in ("both", "buy_low", "sell_high"):\n        direction_filter = "both"\n'
    archive_code = archive_anchor + '''    if max_settlement_hours > 0:
        with SessionLocal() as _di_policy_db:
            _di_policy_db.execute(_di_sa.text("""
              UPDATE dual_inv_paper_decisions
              SET status='CLOSED_POLICY',
                  settled_at_utc=:now,
                  settlement_note=:note,
                  tax_note=:tax_note
              WHERE status='OPEN' AND settle_date_ms > :cutoff_ms
            """), {
                "now": _di_utc_now(),
                "note": "Archived from active paper positions because the current scan horizon is limited to %.1f hours. This record was paper-only; no Binance subscription or fund transfer occurred." % max_settlement_hours,
                "tax_note": "No tax calculated: this paper record was archived, not settled or transferred.",
                "cutoff_ms": _di_now_ms() + int(max_settlement_hours * 3600000),
            })
            _di_policy_db.commit()
'''
    if source.count(archive_anchor) != 1:
        raise RuntimeError("Could not place the 7-day legacy-position policy in the scanner")
    source = source.replace(archive_anchor, archive_code, 1)

    # Share one portfolio budget across simultaneous selections and cap total open exposure.
    alloc_anchor = '''    for candidate in product_candidates:
        if not candidate["selected"] and candidate["decision"] == "ELIGIBLE_PENDING_RANK":
            candidate["decision"] = "NOT_SELECTED"
            candidate["reasons"] = ["Passed basic gates but ranked below the selected offer for the same underlying asset."]
    status = "OK" if product_candidates and markets else ("PARTIAL" if markets or product_candidates else "API_ERROR")
'''
    alloc_replacement = '''    for candidate in product_candidates:
        if not candidate["selected"] and candidate["decision"] == "ELIGIBLE_PENDING_RANK":
            candidate["decision"] = "NOT_SELECTED"
            candidate["reasons"] = ["Passed basic gates but ranked below the selected offer for the same underlying asset."]

    # The configured notional is the total paper budget, not a fresh full-size position for every selected pair.
    with SessionLocal() as _di_budget_db:
        _di_open_rows = _di_budget_db.execute(_di_sa.text("""
          SELECT offer_key, amount_usdt FROM dual_inv_paper_decisions WHERE status='OPEN'
        """)).mappings().all()
    _di_open_by_key = {str(x["offer_key"]): _di_f(x["amount_usdt"], 0) for x in _di_open_rows}
    _di_open_total = sum(_di_open_by_key.values())
    _di_available = max(0.0, amount_usdt - _di_open_total)
    _di_new_selected = [x for x in product_candidates if x["selected"] and x["product_key"] not in _di_open_by_key]
    _di_per_new = (_di_available / len(_di_new_selected)) if _di_new_selected else 0.0
    for _di_candidate in _di_new_selected:
        if _di_per_new < 1.0:
            _di_candidate["selected"] = False
            _di_candidate["decision"] = "CAPITAL_BUDGET_FULL"
            _di_candidate["reasons"].append("The configured total paper budget is already committed to existing open positions.")
        else:
            _di_candidate["allocated_amount_usdt"] = _di_per_new
            _di_scale = _di_per_new / amount_usdt if amount_usdt else 0.0
            for _di_money_field in ("estimated_reward_usdt", "expected_pnl_usdt", "expected_edge_vs_hold_usdt", "p05_pnl_usdt"):
                if _di_candidate.get(_di_money_field) is not None:
                    _di_candidate[_di_money_field] *= _di_scale
    for _di_candidate in product_candidates:
        if _di_candidate["selected"] and _di_candidate["product_key"] in _di_open_by_key:
            _di_candidate["allocated_amount_usdt"] = _di_open_by_key[_di_candidate["product_key"]]

    status = "OK" if product_candidates and markets else ("PARTIAL" if markets or product_candidates else "API_ERROR")
'''
    if source.count(alloc_anchor) != 1:
        raise RuntimeError("Could not install the shared paper-budget allocation gate")
    source = source.replace(alloc_anchor, alloc_replacement, 1)

    # Use the allocated size, not the entire budget, when opening each new paper ledger row.
    source = source.replace('"quote_factor": row["quote_to_usdt"], "amount": amount_usdt,', '"quote_factor": row["quote_to_usdt"], "amount": row.get("allocated_amount_usdt", amount_usdt),', 1)
    # Reward/PnL values have already been scaled to the allocation above.
    source += r'''

# BINANCE_DUAL_INVESTMENT_LIVE_PAPER_MONITOR_V2
import datetime as _di_ui_dt
from sqlalchemy import inspect as _di_ui_inspect

_DI_UI_COLUMNS = {
    "current_spot": "DOUBLE PRECISION",
    "current_value_usdt": "DOUBLE PRECISION",
    "unrealized_pnl_usdt": "DOUBLE PRECISION",
    "unrealized_pnl_pct": "DOUBLE PRECISION",
    "accrued_reward_usdt": "DOUBLE PRECISION",
    "estimated_tax_usdt": "DOUBLE PRECISION",
    "live_price_updated_at": "TEXT",
    "live_price_error": "TEXT",
    "target_gap_pct": "DOUBLE PRECISION",
    "scenario_state": "TEXT",
    "deposit_units": "DOUBLE PRECISION",
    "deposit_currency": "TEXT",
    "mark_method": "TEXT",
    "tax_note": "TEXT",
}

def _di_ui_ensure_schema():
    _di_db_init()
    with SessionLocal() as db:
        dialect = db.get_bind().dialect.name
        existing = {c["name"] for c in _di_ui_inspect(db.get_bind()).get_columns("dual_inv_paper_decisions")}
        for name, typ in _DI_UI_COLUMNS.items():
            if name not in existing:
                db.execute(_di_sa.text("ALTER TABLE dual_inv_paper_decisions ADD COLUMN " + name + " " + typ))
        pk = "BIGSERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        db.execute(_di_sa.text("""
          CREATE TABLE IF NOT EXISTS dual_inv_position_marks (
            id %s,
            offer_key TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            live_price DOUBLE PRECISION,
            current_value_usdt DOUBLE PRECISION,
            unrealized_pnl_usdt DOUBLE PRECISION,
            unrealized_pnl_pct DOUBLE PRECISION,
            accrued_reward_usdt DOUBLE PRECISION,
            target_gap_pct DOUBLE PRECISION,
            scenario_state TEXT,
            tax_estimate_usdt DOUBLE PRECISION,
            UNIQUE(offer_key, observed_at_utc)
          )
        """ % pk))
        db.execute(_di_sa.text("CREATE INDEX IF NOT EXISTS ix_dual_inv_marks_key ON dual_inv_position_marks(offer_key, observed_at_utc)"))
        db.commit()


def _di_ui_archive_policy(max_hours=168.0):
    _di_ui_ensure_schema()
    with SessionLocal() as db:
        db.execute(_di_sa.text("""
          UPDATE dual_inv_paper_decisions
          SET status='CLOSED_POLICY',
              settled_at_utc=:now,
              settlement_note=:note,
              tax_note=:tax_note
          WHERE status='OPEN' AND settle_date_ms > :cutoff_ms
        """), {
            "now": _di_utc_now(),
            "note": "Archived from active paper positions under the 7-day maximum settlement policy. This record was paper-only; no Binance subscription or fund transfer occurred.",
            "tax_note": "No tax calculated: archived paper record, not a settlement or transfer.",
            "cutoff_ms": _di_now_ms() + int(max_hours * 3600000),
        })
        db.commit()


def _di_ui_update_live_positions(persist=True):
    _di_ui_ensure_schema()
    result = {"status": "LIVE", "updated_at_utc": _di_utc_now(), "symbols_updated": 0, "message": ""}
    with SessionLocal() as db:
        positions = db.execute(_di_sa.text("""
          SELECT * FROM dual_inv_paper_decisions WHERE status='OPEN' ORDER BY created_at_utc DESC
        """)).mappings().all()
    if not positions:
        return result
    prices = {}
    errors = []
    symbols = sorted({str(p["symbol"]) for p in positions if p.get("symbol")})
    for symbol in symbols + (["USDCUSDT"] if "USDC" in {str(p.get("deposit_currency") or "") for p in positions} or "USDC" in {str(p.get("pair") or "").split("/")[-1] for p in positions} else []):
        if symbol in prices:
            continue
        try:
            payload = _di_http_json(_DI_API + "/api/v3/ticker/price?" + _di_parse.urlencode({"symbol": symbol}), timeout=10)
            px = _di_f(payload.get("price") if isinstance(payload, dict) else None, 0)
            if px > 0:
                prices[symbol] = px
            else:
                errors.append(symbol + ": no positive live price")
        except Exception as exc:
            errors.append(symbol + ": " + str(exc)[:180])
    if not prices:
        return {"status": "STALE", "updated_at_utc": _di_utc_now(), "symbols_updated": 0, "message": "Live Binance prices unavailable: " + "; ".join(errors[:3])}

    now = _di_now_ms()
    now_utc = _di_utc_now()
    now_dt = _di_ui_dt.datetime.now(_di_ui_dt.timezone.utc)
    mark_bucket = now_dt.replace(minute=(now_dt.minute // 5) * 5, second=0, microsecond=0).isoformat(timespec="seconds").replace("+00:00", "Z")
    saved = 0
    with SessionLocal() as db:
        for pos in positions:
            symbol = str(pos.get("symbol") or "")
            spot = prices.get(symbol)
            if not spot or spot <= 0:
                continue
            direction = str(pos.get("direction") or "")
            target = _di_f(pos.get("target_price"), 0)
            entry = _di_f(pos.get("entry_spot"), spot)
            amount = max(0.0, _di_f(pos.get("amount_usdt"), 0))
            apr = max(0.0, _di_f(pos.get("apr_rate"), 0))
            quote_factor = max(0.000001, _di_f(pos.get("quote_to_usdt"), 1))
            quote_currency = str(pos.get("pair") or "").split("/")[-1].upper()
            current_quote_factor = prices.get("USDCUSDT", quote_factor) if quote_currency == "USDC" else 1.0
            if quote_currency == "USDC" and current_quote_factor <= 0:
                current_quote_factor = quote_factor
            settle = int(_di_f(pos.get("settle_date_ms"), 0))
            created_raw = str(pos.get("created_at_utc") or "")
            try:
                created = _di_ui_dt.datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                elapsed_hours = max(0.0, (now_dt - created.astimezone(_di_ui_dt.timezone.utc)).total_seconds() / 3600.0)
            except Exception:
                elapsed_hours = 0.0
            horizon_hours = max(0.0, (settle - now) / 3600000.0)
            total_hours = max(0.0, _di_f(pos.get("hours_to_settle"), horizon_hours))
            elapsed_hours = min(elapsed_hours, total_hours)
            elapsed_rate = apr * (elapsed_hours / 24.0) / 365.0
            total_rate = apr * (total_hours / 24.0) / 365.0

            if direction == "BUY_LOW":
                deposit_units = amount / quote_factor
                accrued_quote = deposit_units * elapsed_rate
                accrued_reward_usdt = accrued_quote * current_quote_factor
                if target > 0 and spot <= target:
                    scenario_value = (deposit_units + accrued_quote) * (spot / target) * current_quote_factor
                    scenario = "TARGET_TRIGGERED_BUY_LOW"
                else:
                    scenario_value = (deposit_units + accrued_quote) * current_quote_factor
                    scenario = "TARGET_NOT_REACHED_BUY_LOW"
            else:
                deposit_units = amount / (entry * quote_factor) if entry > 0 else 0.0
                accrued_units = deposit_units * elapsed_rate
                accrued_reward_usdt = accrued_units * spot * current_quote_factor
                if target > 0 and spot >= target:
                    scenario_value = (deposit_units + accrued_units) * target * current_quote_factor
                    scenario = "TARGET_TRIGGERED_SELL_HIGH"
                else:
                    scenario_value = (deposit_units + accrued_units) * spot * current_quote_factor
                    scenario = "TARGET_NOT_REACHED_SELL_HIGH"

            projected_reward = amount * total_rate
            unrealized = scenario_value - amount
            pnl_pct = (unrealized / amount * 100.0) if amount > 0 else 0.0
            gap_pct = abs(target / spot - 1.0) * 100.0 if target > 0 and spot > 0 else None
            method = "Scenario valuation at live Binance Spot price; not a tradable mark or early-redemption value."
            error_text = None
            db.execute(_di_sa.text("""
              UPDATE dual_inv_paper_decisions
              SET current_spot=:spot, current_value_usdt=:value,
                  unrealized_pnl_usdt=:pnl, unrealized_pnl_pct=:pnl_pct,
                  accrued_reward_usdt=:accrued, estimated_tax_usdt=0,
                  live_price_updated_at=:updated, live_price_error=:err,
                  target_gap_pct=:gap, scenario_state=:scenario,
                  deposit_units=:units, deposit_currency=:currency, mark_method=:method,
                  tax_note=:tax_note, estimated_reward_usdt=:projected_reward
              WHERE offer_key=:key AND status='OPEN'
            """), {
                "spot": spot, "value": scenario_value, "pnl": unrealized,
                "pnl_pct": pnl_pct, "accrued": accrued_reward_usdt,
                "updated": now_utc, "err": error_text, "gap": gap_pct,
                "scenario": scenario, "units": deposit_units,
                "currency": pos.get("deposit_currency"),
                "method": method, "tax_note": "No open-position tax is assessed. Tax treatment of Dual Investment rewards/conversion depends on the actual transaction and is not determined by this paper model.",
                "projected_reward": projected_reward, "key": pos["offer_key"],
            })
            if persist:
                db.execute(_di_sa.text("""
                  INSERT INTO dual_inv_position_marks
                    (offer_key,observed_at_utc,live_price,current_value_usdt,unrealized_pnl_usdt,
                     unrealized_pnl_pct,accrued_reward_usdt,target_gap_pct,scenario_state,tax_estimate_usdt)
                  VALUES
                    (:key,:observed,:spot,:value,:pnl,:pnl_pct,:accrued,:gap,:scenario,0)
                  ON CONFLICT(offer_key,observed_at_utc) DO NOTHING
                """), {
                    "key": pos["offer_key"], "observed": mark_bucket, "spot": spot,
                    "value": scenario_value, "pnl": unrealized, "pnl_pct": pnl_pct,
                    "accrued": accrued_reward_usdt, "gap": gap_pct, "scenario": scenario,
                })
            saved += 1
        db.commit()
    result["symbols_updated"] = saved
    if errors:
        result["message"] = "Some market marks are stale: " + "; ".join(errors[:3])
    return result


_di_read_state_base_v2 = _di_read_state
def _di_read_state(limit=100):
    _di_ui_ensure_schema()
    _di_ui_archive_policy(168.0)
    live_status = _di_ui_update_live_positions(persist=True)
    state = _di_read_state_base_v2(limit)
    with SessionLocal() as db:
        aggregate = db.execute(_di_sa.text("""
          SELECT
            COALESCE(SUM(CASE WHEN status='OPEN' THEN amount_usdt ELSE 0 END),0) AS invested_open,
            COALESCE(SUM(CASE WHEN status='OPEN' THEN current_value_usdt ELSE 0 END),0) AS current_value_open,
            COALESCE(SUM(CASE WHEN status='OPEN' THEN unrealized_pnl_usdt ELSE 0 END),0) AS unrealized_open,
            COALESCE(SUM(CASE WHEN status='OPEN' THEN estimated_reward_usdt ELSE 0 END),0) AS projected_reward_open,
            COALESCE(SUM(CASE WHEN status='SETTLED_PROXY' THEN paper_pnl_usdt ELSE 0 END),0) AS settled_pnl,
            COALESCE(SUM(CASE WHEN status='SETTLED_PROXY' THEN estimated_tax_usdt ELSE 0 END),0) AS settled_tax,
            COUNT(CASE WHEN status='OPEN' THEN 1 END) AS open_count,
            COUNT(*) AS total_count
          FROM dual_inv_paper_decisions
        """)).mappings().first()
        for item in state.get("paper", []):
            marks = db.execute(_di_sa.text("""
              SELECT observed_at_utc,live_price,current_value_usdt,unrealized_pnl_usdt,unrealized_pnl_pct
              FROM dual_inv_position_marks WHERE offer_key=:key
              ORDER BY observed_at_utc DESC LIMIT 24
            """), {"key": item.get("offer_key")}).mappings().all()
            item["mark_history"] = [dict(m) for m in reversed(marks)]
            item["latest_mark_price"] = item.get("current_spot")
    settled_pnl = _di_f((aggregate or {}).get("settled_pnl"), 0)
    settled_tax = _di_f((aggregate or {}).get("settled_tax"), 0)
    stats = state.setdefault("stats", {})
    stats.update({
        "invested_open_usdt": _di_f((aggregate or {}).get("invested_open"), 0),
        "current_value_open_usdt": _di_f((aggregate or {}).get("current_value_open"), 0),
        "unrealized_pnl_open_usdt": _di_f((aggregate or {}).get("unrealized_open"), 0),
        "projected_reward_open_usdt": _di_f((aggregate or {}).get("projected_reward_open"), 0),
        "estimated_settled_tax_usdt": settled_tax,
        "settled_pnl_usdt": settled_pnl,
        "settled_after_tax_pnl_usdt": settled_pnl - settled_tax,
        "paper_positions_total": int(_di_f((aggregate or {}).get("total_count"), 0)),
        "open_paper_decisions": int(_di_f((aggregate or {}).get("open_count"), 0)),
    })
    state["live_status"] = live_status
    return state


_di_settle_matured_base_v2 = _di_settle_matured
def _di_settle_matured():
    settled = _di_settle_matured_base_v2()
    _di_ui_ensure_schema()
    with SessionLocal() as db:
        db.execute(_di_sa.text("""
          UPDATE dual_inv_paper_decisions
          SET estimated_tax_usdt = CASE WHEN COALESCE(paper_pnl_usdt,0)>0 THEN paper_pnl_usdt*0.30 ELSE 0 END,
              tax_note = CASE
                WHEN COALESCE(paper_pnl_usdt,0)>0 THEN 'Illustrative reserve: 30% of positive settled paper PnL only if VDA-transfer treatment applies. Excludes cess/surcharge; actual Dual Investment tax character not determined.'
                ELSE 'No positive settled paper PnL; no illustrative VDA-transfer base tax reserve estimated. Actual tax treatment may differ.'
              END
          WHERE status='SETTLED_PROXY'
        """))
        db.commit()
    return settled

# Background scans persist live marks even if the dashboard is not open.
_bg_marker = '            app.logger.info(\n                "dual_investment_background_scan_completed'
_bg_replacement = '''            try:
                _di_ui_update_live_positions(persist=True)
            except Exception:
                app.logger.exception("dual_investment_live_mark_failed")
            app.logger.info(
                "dual_investment_background_scan_completed'''
if source.count(_bg_marker) == 1:
    source = source.replace(_bg_marker, _bg_replacement, 1)

'''
    APP_PATH.write_text(source)

print("Installed responsive Dual Investment live paper dashboard, 7-day default, current-price mark ledger, shared budget cap, and tax/loss visibility.")
