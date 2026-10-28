from pathlib import Path

APP = Path("/app/app.py")
source = APP.read_text()

def replace_once(old, new, label):
    global source
    count = source.count(old)
    if count != 1:
        raise RuntimeError("Duration filter patch expected exactly one " + label + " anchor; found " + str(count))
    source = source.replace(old, new, 1)

if "BINANCE_DUAL_INVESTMENT_DURATION_FILTER_V1" not in source:
    replace_once(
        "def _di_scan(amount_usdt, direction_filter, max_distance, max_tail_loss_pct):",
        "def _di_scan(amount_usdt, direction_filter, max_distance, max_tail_loss_pct, max_settlement_hours=24):",
        "scan function signature"
    )
    replace_once(
        '    max_tail_loss_pct = max(0.1, min(20.0, _di_f(max_tail_loss_pct, 3.0)))\n    if direction_filter not in ("both", "buy_low", "sell_high"):',
        '    max_tail_loss_pct = max(0.1, min(20.0, _di_f(max_tail_loss_pct, 3.0)))\n    max_settlement_hours = max(0.0, min(720.0, _di_f(max_settlement_hours, 24.0)))\n    if direction_filter not in ("both", "buy_low", "sell_high"):',
        "duration settings"
    )
    replace_once(
        '''                        row = _di_evaluate_offer(product, pair, direction, markets[pair["symbol"]], quote_factor,
                                                 amount_usdt, max_distance, max_tail_loss_pct)
                        if row["settle_date_ms"] <= _di_now_ms():''',
        '''                        row = _di_evaluate_offer(product, pair, direction, markets[pair["symbol"]], quote_factor,
                                                 amount_usdt, max_distance, max_tail_loss_pct)
                        if max_settlement_hours > 0 and row["hours_to_settle"] > max_settlement_hours:
                            row["reasons"].append("Settlement is %.1f hours away, beyond the %.1f-hour horizon filter" % (row["hours_to_settle"], max_settlement_hours))
                            if row["decision"] == "ELIGIBLE_PENDING_RANK":
                                row["decision"] = "REJECTED"
                        if row["settle_date_ms"] <= _di_now_ms():''',
        "offer duration gate"
    )
    replace_once(
        '    market_payload["api_methods"] = sorted(api_methods)\n    with SessionLocal() as db:',
        '    market_payload["api_methods"] = sorted(api_methods)\n    market_payload["scan_config"] = {\n        "amount_usdt": amount_usdt,\n        "direction_filter": direction_filter,\n        "max_target_distance_pct": max_distance,\n        "max_tail_loss_pct": max_tail_loss_pct,\n        "max_settlement_hours": max_settlement_hours,\n    }\n    with SessionLocal() as db:',
        "persisted scan configuration"
    )
    replace_once(
        '        "direction_filter": direction_filter, "products_fetched": len(product_candidates),',
        '        "direction_filter": direction_filter, "max_settlement_hours": max_settlement_hours,\n        "products_fetched": len(product_candidates),',
        "scan response configuration"
    )
    replace_once(
        '            args.get("max_tail_loss_pct", 3)\n        )',
        '            args.get("max_tail_loss_pct", 3),\n            args.get("max_settlement_hours", 24)\n        )',
        "scan route argument"
    )
    replace_once(
        '                max_tail_loss_pct=_di_bg_os.environ.get("DI_MAX_TAIL_LOSS_PCT", "3"),\n            )',
        '                max_tail_loss_pct=_di_bg_os.environ.get("DI_MAX_TAIL_LOSS_PCT", "3"),\n                max_settlement_hours=_di_bg_os.environ.get("DI_MAX_SETTLEMENT_HOURS", "24"),\n            )',
        "background worker duration"
    )

    replace_once(
        '.controls{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr)) auto;gap:12px;align-items:end}',
        '.controls{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr)) auto;gap:12px;align-items:end}',
        "responsive controls grid"
    )
    replace_once(
        '<div class="field"><label for="di-distance">Max target distance (%)</label><input id="di-distance" type="number" min="0.1" max="25" step="0.1" value="5"></div>\n<div class="field"><label for="di-tail">Max historical P05 loss (%)</label>',
        '<div class="field"><label for="di-distance">Max target distance (%)</label><input id="di-distance" type="number" min="0.1" max="25" step="0.1" value="5"></div>\n<div class="field"><label for="di-duration">Max time to settlement</label><select id="di-duration"><option value="8">Up to 8 hours</option><option value="24" selected>Up to 24 hours</option><option value="48">Up to 48 hours</option><option value="168">Up to 7 days</option><option value="720">Up to 30 days</option><option value="0">All available</option></select></div>\n<div class="field"><label for="di-tail">Max historical P05 loss (%)</label>',
        "duration control"
    )
    replace_once(
        '<th>Reward / 150 USDT</th>',
        '<th>Estimated reward</th>',
        "reward table heading"
    )
    replace_once(
        'max_target_distance_pct:Number($("di-distance").value||5),max_tail_loss_pct:Number($("di-tail").value||3)',
        'max_target_distance_pct:Number($("di-distance").value||5),max_tail_loss_pct:Number($("di-tail").value||3),max_settlement_hours:Number($("di-duration").value||24)',
        "frontend scan payload"
    )
    replace_once(
        '<th>Direction filter</th><th>Market data</th><th>API diagnostics</th>',
        '<th>Direction filter</th><th>Max duration</th><th>Market data</th><th>API diagnostics</th>',
        "scan history table header"
    )
    placeholder = '<td colspan="7" class="empty">No scans recorded yet.</td>'
    if source.count(placeholder) != 2:
        raise RuntimeError("Expected the empty scan placeholder in the static table and JS renderer")
    source = source.replace(placeholder, '<td colspan="8" class="empty">No scans recorded yet.</td>')

    source += "\n# BINANCE_DUAL_INVESTMENT_DURATION_FILTER_V1\n"
    APP.write_text(source)

print("Installed selectable settlement-horizon risk gate (default 24h, editable through 30d or all) and persisted scan configuration.")
