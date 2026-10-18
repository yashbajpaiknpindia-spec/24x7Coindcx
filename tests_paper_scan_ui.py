"""Static contract check that scan results are exposed and rendered without mock market prices."""
from pathlib import Path

main = Path("app/main.py").read_text(encoding="utf-8")
template = Path("app/templates/paper.html").read_text(encoding="utf-8")
core = Path("app/core.py").read_text(encoding="utf-8")
assert "@app.get('/api/paper-scan-results')" in main
assert "paper_strategy_scan" in main and "paper_strategy_scan" in core
for marker in ("paper-scan-table", "scan-summary-markets", "scan-summary-liquid",
               "scan-summary-opportunities", "scan-summary-candles",
               "scan-results-error", "data-scan-filter", "setInterval(poll,10000)"):
    assert marker in template, f"missing live scan UI marker: {marker}"
# The UI must contain no fabricated sample rows; fixtures belong only in offline tests.
assert "B-BTC_USDT 25000" not in template and "COIN000_USDT" not in template
print("PASS: paper UI renders scan rows, opportunity/quality metrics and visible data errors.")
