from pathlib import Path
root = Path("/app")

def show(path, rules, budget=75):
    p = root / path
    if not p.exists():
        print("RUNTIME_INSPECT", path, "MISSING")
        return
    lines = p.read_text(errors="replace").splitlines()
    picks = set()
    for i, line in enumerate(lines):
        if any(rule.lower() in line.lower() for rule in rules):
            picks.update(range(max(0, i-2), min(len(lines), i+3)))
    print("RUNTIME_INSPECT_START", path, "lines", len(lines))
    for i in sorted(picks)[:budget]:
        line = lines[i].replace("\t", " ")
        if any(secret in line.lower() for secret in ("os.getenv('app_password'", 'os.getenv("app_password"', 'binance_api_secret')):
            # Show the configuration variable name only, never any runtime value.
            line = "[secret-related line redacted]"
        print(f"{i+1}: {line[:240]}")
    print("RUNTIME_INSPECT_END", path)

show("app.py", [
    "Authentication required", "authentication_required", "before_request", "login_required",
    "session[", "session.get", "def login", "def api_status", "/api/status", "/api/overview",
    "/api/system", "/api/multi-trader", "def health", "app.secret_key", "PERMANENT_SESSION"
], 100)
show("static/app.js", [
    "async function api", "function api(", "credentials:", "loadOverview", "refreshStatus",
    "loadSystem()", "DOMContentLoaded", "plRunForecast", "function view(", "data-view"
], 100)
show("templates/index.html", ["static/app.js", "stylesheet", "script src"], 25)
show("static/style.css", ["body{", "font-size:", "table", "--font", "label{", ".kpi-value"], 60)
