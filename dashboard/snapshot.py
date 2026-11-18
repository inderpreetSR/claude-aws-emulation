"""Save a read-only copy of the dashboard, with everything the emulator holds, as one HTML file.

    python dashboard/snapshot.py                      # writes dashboard-snapshot.html
    python dashboard/snapshot.py out.html --fragment  # page body only, for hosts that add their own <html>/<head>

Useful for sharing what a lab built, or for viewing it where the live dashboard cannot be reached.
The copy has every list and drill-down view, plus one saved Athena query result.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import server  # noqa: E402  (the live dashboard's own view functions)

SAMPLE_SQL = """SELECT segment, COUNT(*) AS loans, AVG(defaulted) AS default_rate
FROM loans
GROUP BY segment
ORDER BY default_rate DESC"""


def encode(key: str) -> str:
    """The same encoding the page's encodeURIComponent uses, so drill-down lookups match."""
    return quote(str(key), safe="!*'()")


def collect() -> dict:
    s = server.emu.settings()
    views = [{"id": k, "group": g, "label": l} for k, (g, l, _, show) in server.VIEWS.items() if show]
    responses = {"/api/status": {"healthy": server.emu.health(), "endpoint": s["endpoint_url"],
                                 "region": s["region_name"], "views": views}}
    counts = {}
    for v in views:
        try:
            data = server.VIEWS[v["id"]][2]({})
        except Exception as e:  # a view the emulator refuses still shows its reason
            data = {"error": server.short_error(e)}
        responses[f"/api/view/{v['id']}"] = data
        counts[v["id"]] = None if "error" in data else len(data["rows"])
        drill = data.get("drill")
        for row in data.get("rows", []) if drill else []:
            key = row[data.get("key_col", 0)]
            try:
                responses[f"/api/view/{drill}?key={encode(key)}"] = server.VIEWS[drill][2]({"key": key})
            except Exception as e:
                responses[f"/api/view/{drill}?key={encode(key)}"] = {"error": server.short_error(e)}
    responses["/api/counts"] = counts

    databases = [r[0] for r in responses["/api/view/glue_databases"].get("rows", [])]
    database = "lending" if "lending" in databases else (databases[0] if databases else "")
    try:
        result = server.run_athena(SAMPLE_SQL, database or None)
    except Exception as e:
        result = {"error": server.short_error(e)}
    return {"taken": dt.datetime.now().strftime("%d %b %Y %H:%M"), "responses": responses,
            "athena": {"sql": SAMPLE_SQL, "database": database, "result": result}}


def build(fragment: bool) -> str:
    page = (HERE / "index.html").read_text()
    data = json.dumps(collect(), default=str).replace("</", "<\\/")
    page = page.replace("<script>\nconst $", f"<script>window.SNAPSHOT = {data};</script>\n<script>\nconst $", 1)
    if fragment:  # keep <title>, <meta>, <style> and the body's contents
        head = re.search(r"<head>(.*?)</head>", page, re.S).group(1)
        head = re.sub(r'<meta charset[^>]*>\s*|<meta name="viewport"[^>]*>\s*', "", head)
        body = re.search(r"<body>(.*)</body>", page, re.S).group(1)
        page = head.strip() + "\n" + body.strip() + "\n"
    return page


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0] if args else "dashboard-snapshot.html")
    out.write_text(build("--fragment" in sys.argv))
    print(f"Saved {out} ({out.stat().st_size // 1024} KB)")
