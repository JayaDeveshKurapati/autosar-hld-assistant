"""Printable HTML review report (print to PDF from the browser)."""
from __future__ import annotations

import time
from html import escape as e

CSS = """body{font:14px/1.5 system-ui,Segoe UI,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;color:#1b1f24}
h1{font-size:1.6rem}h2{margin-top:2rem;border-bottom:1px solid #d0d7de;padding-bottom:.2rem}
table{border-collapse:collapse;width:100%;margin:.5rem 0}th,td{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa}.error{color:#b42318;font-weight:600}.warning{color:#b54708;font-weight:600}.info{color:#175cd3}
.sign td{height:2.4rem}small{color:#57606a}"""


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "<p><small>None.</small></p>"
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c if isinstance(c, _Raw) else e(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


class _Raw(str):
    pass


def build(doc: dict, summary: dict, findings: list[dict], reqs: list[dict], chains: list[dict], tests: list[dict]) -> str:
    sev = {k: sum(1 for f in findings if f["severity"] == k) for k in ("error", "warning", "info")}
    reviewed = sum(1 for f in findings if f["review"])
    ex = doc["extraction"]
    parts = [
        f"<!doctype html><meta charset=utf-8><title>HLD review - {e(doc['name'])}</title><style>{CSS}</style>",
        f"<h1>HLD analysis review report</h1><p><b>{e(doc['name'])}</b> version {e(doc['version'])} "
        f"(status: {e(doc['status'])}, {doc['pages']} pages)<br><small>Generated {time.strftime('%Y-%m-%d %H:%M')}. "
        "AI-assisted extraction: an authorised engineer must review before any design approval.</small></p>",
        "<h2>Summary</h2>", _table(list(summary), [list(summary.values())]),
        f"<p>Findings: <span class=error>{sev['error']} errors</span>, <span class=warning>{sev['warning']} warnings</span>, "
        f"<span class=info>{sev['info']} info</span>; {reviewed} of {len(findings)} reviewed.</p>",
        "<h2>Findings</h2>",
        _table(["Severity", "Rule", "Finding", "Source", "Review"],
               [[_Raw(f"<span class={f['severity']}>{f['severity']}</span>"), f["rule"], f["message"],
                 f"p.{f['page']} {f['section']}",
                 (f"{f['review']['decision']} ({f['review']['reviewer']}): {f['review']['note'] or ''}" if f["review"] else "open")]
                for f in findings]),
        "<h2>Components</h2>",
        _table(["Component", "Kind", "Source"], [[n, c["kind"], f"p.{c['page']} {c['section']}"] for n, c in ex.components.items()]),
        "<h2>Connections</h2>",
        _table(["From", "To", "Source"], [[f"{c['from_comp']}.{c['from_port']}", f"{c['to_comp']}.{c['to_port']}",
                                          f"p.{c['page']}"] for c in ex.connections]),
        "<h2>Requirements</h2>",
        _table(["ID", "Kind", "Text", "Linked entities", "Source"],
               [[r["id"], r["kind"], r["text"], ", ".join(x["name"] for x in r["entities"]) or "-", f"p.{r['page']}"] for r in reqs]),
        "<h2>End-to-end chains (estimated)</h2>",
        _table(["Chain", "Est. latency (ms)", "Unknown periods"],
               [[" -> ".join(c["path"]), f"{c['latency_ms']:g}", ", ".join(c["unknown"]) or "-"] for c in chains]),
        f"<h2>Generated test plan</h2><p>{len(tests)} test case skeletons (see tests.csv in the export).</p>",
        "<h2>Sign-off</h2>",
        "<table class=sign><tr><th>Role</th><th>Name</th><th>Signature</th><th>Date</th></tr>"
        "<tr><td>Author / reviewer</td><td></td><td></td><td></td></tr>"
        "<tr><td>Architecture approver</td><td></td><td></td><td></td></tr></table>",
    ]
    return "\n".join(parts)
