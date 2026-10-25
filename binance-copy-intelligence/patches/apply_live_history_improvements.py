from pathlib import Path
import re

root = Path("/app")
collector_path = root / "collector.py"
src = collector_path.read_text()

# The old candidate list had incorrect routes. Add the Spot-specific Binance Copy Trading
# API family before falling back to older candidate URLs.
src = src.replace(
    'SPOT_LIST_CANDIDATES = [\n',
    'SPOT_LIST_CANDIDATES = [\n    "/bapi/futures/v1/friendly/future/spot-copy-trade/common/home-page-list",\n',
    1,
)
src = src.replace(
    'SPOT_HISTORY_CANDIDATES = [\n',
    'SPOT_HISTORY_CANDIDATES = [\n    "/bapi/futures/v1/friendly/future/spot-copy-trade/lead-portfolio/get-trade-history-by-page",\n',
    1,
)

def replace_method(text, method_name, replacement):
    lines = text.splitlines(True)
    start = next((i for i, line in enumerate(lines)
                  if line.startswith(f"    def {method_name}(")), None)
    if start is None:
        raise RuntimeError(f"Could not find collector method {method_name}")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        if line.startswith("    def ") or line.startswith("    @"):
            end = i
            break
        if not line.startswith((" ", "\t", "#")):
            end = i
            break
    replacement_text = replacement.rstrip() + "\n\n"
    return "".join(lines[:start]) + replacement_text + "".join(lines[end:])

list_method = r'''    def list_spot(self, page: int, time_range: str, data_type: str) -> dict:
        # This Spot-specific listing endpoint uses a slightly different payload from Futures.
        # The supported period variants are 30D/90D/180D/365D. Do not label a 30D value as 7D.
        if str(time_range).upper() == "7D":
            return {"code": "000000", "success": True,
                    "data": {"list": [], "total": 0},
                    "_source_note": "Spot leaderboard has no verified 7D period in this collector."}
        if str(time_range).upper() not in ("30D", "90D", "180D", "365D"):
            raise SourceError(f"Unsupported Spot leaderboard period: {time_range}")
        payload = {
            "dataType": data_type,
            "favoriteOnly": False,
            "hideFull": False,
            "order": "DESC",
            "pageNumber": int(page),
            "pageSize": 30,
            "portfolioType": "ALL",
            "timeRange": str(time_range).upper(),
            "useAiRecommended": False,
            "userAsset": 0,
            "nickname": "",
        }
        paths = []
        if self.spot_list_path:
            paths.append(self.spot_list_path)
        paths.extend(SPOT_LIST_CANDIDATES)
        seen = set()
        last_error = None
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                response = self.post(path, payload)
                normalized = _spot_response_with_list(response)
                if normalized is not None:
                    self.spot_list_path = path
                    return normalized
                last_error = f"{path}: response data did not contain a recognized list/rows array"
            except Exception as exc:
                last_error = f"{path}: {str(exc)[:220]}"
        raise SourceError("No verified Spot listing response. Last probe: " + str(last_error)[:300])'''

history_method = r'''    def history_spot(self, portfolio_id: str, page: int, page_size: int = 50) -> dict:
        payload = {
            "portfolioId": str(portfolio_id),
            "pageNumber": int(page),
            "pageSize": int(page_size),
        }
        paths = []
        if self.spot_history_path:
            paths.append(self.spot_history_path)
        paths.extend(SPOT_HISTORY_CANDIDATES)
        seen = set()
        last_error = None
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                response = self.post(path, payload)
                normalized = _spot_response_with_list(response)
                if normalized is not None:
                    self.spot_history_path = path
                    return normalized
                last_error = f"{path}: response data did not contain a recognized list/rows array"
            except Exception as exc:
                last_error = f"{path}: {str(exc)[:220]}"
        raise SourceError("No verified Spot lead trade-history response. Last probe: " + str(last_error)[:300])'''

src = replace_method(src, "list_spot", list_method)
src = replace_method(src, "history_spot", history_method)

normalizer = r'''

def _spot_response_with_list(response):
    """Normalize Spot copy-trading response variants without fabricating records."""
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("list", "rows", "items", "records"):
        if isinstance(data.get(key), list):
            if key == "list":
                return response
            result = dict(response)
            result["data"] = dict(data)
            result["data"]["list"] = data[key]
            return result
    return None
'''
if "def _spot_response_with_list(" not in src:
    src += normalizer
collector_path.write_text(src)

# Skip the unsupported 7D Spot mode instead of treating its intentional empty response
# as proof that the Spot leaderboard contains no profiles.
discovery_src = collector_path.read_text()
if "SPOT_SUPPORTED_PERIODS_V1" not in discovery_src:
    old_modes = 'modes = [(r, t) for r in (("7D", "30D", "90D", "180D", "365D") if include_older else ("7D", "30D", "365D")) for t in ("ROI", "PNL", "SHARP_RATIO", "WIN_RATE", "AUM")]'
    new_modes = '''# SPOT_SUPPORTED_PERIODS_V1: do not query unsupported 7D Spot periods.
    periods = ("30D", "90D", "180D", "365D") if market_type == "SPOT" else (("7D", "30D", "90D", "180D", "365D") if include_older else ("7D", "30D", "365D"))
    modes = [(r, t) for r in periods for t in ("ROI", "PNL", "SHARP_RATIO", "WIN_RATE", "AUM")]'''
    if discovery_src.count(old_modes) != 1:
        raise RuntimeError(f"Spot period selection anchor count={discovery_src.count(old_modes)}")
    collector_path.write_text(discovery_src.replace(old_modes, new_modes, 1))


# Prefer recently closed trades for prompt MAE/MFE feedback; older backlog remains eligible.
analytics_path = root / "analytics.py"
if analytics_path.exists():
    a = analytics_path.read_text()
    old_order = 'stmt = stmt.order_by((Position.path_status == "RATE_LIMIT_DEFERRED").desc(), Position.path_analyzed_at.asc().nullsfirst(), Position.closed_ms.asc().nullsfirst())'
    new_order = 'stmt = stmt.order_by((Position.path_status == "RATE_LIMIT_DEFERRED").desc(), Position.closed_ms.desc().nullslast(), Position.path_analyzed_at.asc().nullsfirst())'
    if new_order not in a:
        if a.count(old_order) != 1:
            raise RuntimeError(f"Path-priority anchor count={a.count(old_order)}")
        a = a.replace(old_order, new_order, 1)
        analytics_path.write_text(a)

# Correct official detail links to the route pattern already used in the confirmed portfolio URLs.
# For Spot, Binance's Spot-specific API also builds its detail-page referer on /copy-trading/lead-details/<id>.
app_path = root / "app.py"
app = app_path.read_text()
if "PORTFOLIO_OFFICIAL_LINKS_V2" not in app:
    start = app.find("def _pl_url(t):")
    if start != -1:
        end = app.find("\ndef _pl_row(", start)
        if end == -1:
            raise RuntimeError("Could not locate end of _pl_url helper")
        helper = '''def _pl_url(t):
    if not t.portfolio_id:
        return None
    return "https://www.binance.com/en-IN/copy-trading/lead-details/" + str(t.portfolio_id) + "?timeRange=90D"

'''
        app = app[:start] + helper + app[end+1:]
    # Ensure every already-stored Binance profile uses the verified detail URL, not a guessed market subpath.
    app += '''

# PORTFOLIO_OFFICIAL_LINKS_V2: migrate saved profile URLs to the current official detail route.
try:
    with SessionLocal() as _link_db:
        _link_rows = list(_link_db.scalars(select(Trader).where(Trader.exchange == "BINANCE")))
        _link_changed = 0
        for _t in _link_rows:
            if _t.portfolio_id:
                _good_url = "https://www.binance.com/en-IN/copy-trading/lead-details/" + str(_t.portfolio_id) + "?timeRange=90D"
                if _t.profile_url != _good_url:
                    _t.profile_url = _good_url
                    _link_changed += 1
        if _link_changed:
            _link_db.commit()
            app.logger.info("portfolio_official_links_migrated count=%s", _link_changed)
except Exception:
    app.logger.exception("portfolio_official_links_migration_failed")
'''
    app_path.write_text(app)

print("Spot listing/history endpoints updated; newest closed trades prioritized; official portfolio links normalized.")
