from pathlib import Path
import re

root = Path("/app")
html_path = root / "templates" / "index.html"
js_path = root / "static" / "app.js"
html = html_path.read_text()
js = js_path.read_text()

if not js.strip():
    raise RuntimeError("static/app.js is empty after the build patches")

# Cache-bust the main client bundle on every build generation. This prevents a
# browser from continuing to execute a stale, previously broken app.js.
pattern = re.compile(
    r'(?P<prefix><script\b[^>]*\bsrc\s*=\s*)(?P<q>["\'])(?P<src>.*?app\.js.*?)(?P=q)(?P<suffix>[^>]*>)',
    re.IGNORECASE | re.DOTALL
)
matches = list(pattern.finditer(html))
if len(matches) != 1:
    raise RuntimeError(f"Expected exactly one app.js script include in index.html; found {len(matches)}")

version = "bi-frontend-20261028-tax1"
m = matches[0]
replacement = m.group("prefix") + m.group("q") + m.group("src") + "?v=" + version + m.group("q") + m.group("suffix")
html = html[:m.start()] + replacement + html[m.end():]
html_path.write_text(html)

# Keep the HTML and generated JS tied to the same build version for diagnostics.
print(f"Frontend asset cache-busted: {version}; app.js bytes={len(js.encode('utf-8'))}")
