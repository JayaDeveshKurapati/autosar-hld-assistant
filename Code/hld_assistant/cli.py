"""Command line: usable as a CI gate.

  python -m hld_assistant analyze hld.pdf --fail-on error
  python -m hld_assistant compare old.txt new.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import Service
from .store import Store

RANK = {"info": 0, "warning": 1, "error": 2}


def _load(svc: Service, path: str) -> int:
    p = Path(path)
    return svc.ingest("cli", p.name, p.read_bytes())["doc_id"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hld_assistant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="run consistency checks on one document")
    a.add_argument("file")
    a.add_argument("--json", action="store_true")
    a.add_argument("--fail-on", choices=["error", "warning", "never"], default="error")
    c = sub.add_parser("compare", help="structural + text diff between two revisions")
    c.add_argument("old")
    c.add_argument("new")
    args = ap.parse_args(argv)
    svc = Service(Store(":memory:"))

    if args.cmd == "analyze":
        doc = _load(svc, args.file)
        findings = svc.findings(doc)
        if args.json:
            print(json.dumps({"summary": svc.summary(doc), "findings": findings}, indent=2))
        else:
            print(f"{args.file}: {svc.summary(doc)}")
            for f in findings:
                print(f"[{f['severity'].upper():7}] {f['rule']}: {f['message']} (p.{f['page']}, {f['section']})")
        if args.fail_on == "never":
            return 0
        return 1 if any(RANK[f["severity"]] >= RANK[args.fail_on] for f in findings) else 0

    old, new = _load(svc, args.old), _load(svc, args.new)
    for r in svc.compare(old, new):
        print(f"{r['change']:8} {r['kind']}: {r['item']} {r['detail']}".rstrip())
    for r in svc.text_diff(old, new):
        for v in r["value_changes"]:
            print(f"value    {r['section']}: {v['old']} -> {v['new']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
