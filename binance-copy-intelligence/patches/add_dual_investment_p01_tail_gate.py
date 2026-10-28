from pathlib import Path

APP = Path("/app/app.py")
source = APP.read_text()

def replace_once(old, new, label):
    global source
    n = source.count(old)
    if n != 1:
        raise RuntimeError("P01 tail-gate patch expected exactly one " + label + " anchor; found " + str(n))
    source = source.replace(old, new, 1)

if "BINANCE_DUAL_INVESTMENT_P01_TAIL_GATE_V1" not in source:
    replace_once(
        '    p05_pnl = _di_percentile(pnl_samples, 0.05)\n    sample_count = len(ratios)',
        '    p05_pnl = _di_percentile(pnl_samples, 0.05)\n    p01_pnl = _di_percentile(pnl_samples, 0.01)\n    sample_count = len(ratios)',
        "P01 percentile calculation"
    )
    replace_once(
        '    if p05_pnl is not None and p05_pnl < -(amount_usdt * max_tail_loss_pct / 100.0):\n        reasons.append("Historical 5th-percentile simulated PnL breaches the %.2f%% loss gate" % max_tail_loss_pct)',
        '    if p05_pnl is not None and p05_pnl < -(amount_usdt * max_tail_loss_pct / 100.0):\n        reasons.append("Historical 5th-percentile simulated PnL breaches the %.2f%% loss gate" % max_tail_loss_pct)\n    if p01_pnl is not None and p01_pnl < -(amount_usdt * max_tail_loss_pct / 100.0):\n        reasons.append("Historical 1st-percentile simulated PnL of %.4f USDT breaches the %.2f%% loss gate" % (p01_pnl, max_tail_loss_pct))',
        "P01 tail-loss gate"
    )
    replace_once(
        '<strong>Historic exercise proxy:</strong> rolling hourly close-to-close returns of the same estimated duration are tested against the current target/spot ratio. This ignores the exact 30-minute fixing mechanics, fees/spreads, structural market changes, and execution constraints. The P05 result is an empirical lower-tail proxy, not a worst-case bound.<br>',
        '<strong>Historic exercise proxy:</strong> rolling hourly close-to-close returns of the same estimated duration are tested against the current target/spot ratio. This ignores the exact 30-minute fixing mechanics, fees/spreads, structural market changes, and execution constraints. The P05 result is an empirical lower-tail proxy, not a worst-case bound.<br><strong>Conservative tail gate:</strong> selection checks both the historical 5th and 1st percentile against your maximum-loss threshold; moves outside historical samples can still be worse.<br>',
        "tail-risk explanation"
    )
    source += "\n# BINANCE_DUAL_INVESTMENT_P01_TAIL_GATE_V1\n"
    APP.write_text(source)

print("Installed a 1st-percentile historical tail-loss gate alongside the 5th-percentile gate.")
