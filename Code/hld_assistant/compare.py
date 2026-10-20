"""Revision comparison between two extractions (old -> new)."""
from __future__ import annotations

import difflib
import re

from .extract import Extraction
from .ingest import HEADING_RE


_VALUE = re.compile(r"\d+(?:\.\d+)?\s*(?:ms|us|s|Hz|kHz|V|A|%|bit|byte|bytes)\b")
_NUM_PREFIX = re.compile(r"^\d+(?:\.\d+)*\.?\s+")


def _sections(chunks) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in chunks:
        key = _NUM_PREFIX.sub("", c.section)
        lines = [ln.strip() for ln in c.text.splitlines() if ln.strip()]
        if lines and HEADING_RE.match(lines[0]):
            lines = lines[1:]  # heading is the key; its number may legitimately change between revisions
        out.setdefault(key, []).extend(lines)
    return out


def section_diff(old_chunks, new_chunks) -> list[dict]:
    """Section-level text diff. Catches changes the structural diff cannot see (e.g. 20 ms -> 15 ms)."""
    a, b = _sections(old_chunks), _sections(new_chunks)
    rows = []
    for key in list(dict.fromkeys(list(a) + list(b))):
        if key not in b:
            rows.append({"section": key, "status": "removed", "diff": "", "value_changes": []})
        elif key not in a:
            rows.append({"section": key, "status": "added", "diff": "", "value_changes": []})
        elif a[key] != b[key]:
            sm = difflib.SequenceMatcher(None, a[key], b[key], autojunk=False)
            diff, values = [], []
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == "equal":
                    continue
                diff += [f"- {x}" for x in a[key][i1:i2]] + [f"+ {x}" for x in b[key][j1:j2]]
                if op == "replace" and i2 - i1 == j2 - j1:
                    for x, y in zip(a[key][i1:i2], b[key][j1:j2]):
                        vx, vy = _VALUE.findall(x), _VALUE.findall(y)
                        values += [{"old": p, "new": q} for p, q in zip(vx, vy) if p != q]
            rows.append({"section": key, "status": "changed", "diff": "\n".join(diff), "value_changes": values})
    return rows


def _port_map(ex: Extraction) -> dict[str, dict]:
    return {f"{p.component}.{p.name}": {"direction": p.direction, "interface": p.interface,
                                         "signal": p.signal, "dtype": p.dtype, "page": p.page}
            for p in ex.ports}


def _conn_set(ex: Extraction) -> set[str]:
    return {f"{c['from_comp']}.{c['from_port']} -> {c['to_comp']}.{c['to_port']}" for c in ex.connections}


def compare(old: Extraction, new: Extraction) -> list[dict]:
    """Return a flat list of {kind, change, item, detail} rows."""
    rows: list[dict] = []

    def add(kind, change, item, detail=""):
        rows.append({"kind": kind, "change": change, "item": item, "detail": detail})

    def diff_keys(kind, a, b):
        for k in sorted(set(b) - set(a)):
            add(kind, "added", k)
        for k in sorted(set(a) - set(b)):
            add(kind, "removed", k)

    diff_keys("component", old.components, new.components)
    diff_keys("interface", old.interfaces, new.interfaces)
    for name in sorted(set(old.interfaces) & set(new.interfaces)):
        a, b = old.interfaces[name]["elements"], new.interfaces[name]["elements"]
        for el in sorted(set(a) | set(b)):
            if el not in a:
                add("interface element", "added", f"{name}.{el}", b[el])
            elif el not in b:
                add("interface element", "removed", f"{name}.{el}", a[el])
            elif a[el] != b[el]:
                add("interface element", "changed", f"{name}.{el}", f"{a[el]} -> {b[el]}")

    pa, pb = _port_map(old), _port_map(new)
    diff_keys("port", pa, pb)
    for k in sorted(set(pa) & set(pb)):
        for attr in ("direction", "interface", "signal", "dtype"):
            if pa[k][attr] != pb[k][attr]:
                add("port", "changed", k, f"{attr}: {pa[k][attr]} -> {pb[k][attr]}")

    ca, cb = _conn_set(old), _conn_set(new)
    for c in sorted(cb - ca):
        add("connection", "added", c)
    for c in sorted(ca - cb):
        add("connection", "removed", c)

    ra = {(r["component"], r["name"]): r["period"] for r in old.runnables}
    rb = {(r["component"], r["name"]): r["period"] for r in new.runnables}
    for k in sorted(set(rb) - set(ra)):
        add("runnable", "added", f"{k[0]}.{k[1]}")
    for k in sorted(set(ra) - set(rb)):
        add("runnable", "removed", f"{k[0]}.{k[1]}")
    for k in sorted(set(ra) & set(rb)):
        if ra[k] != rb[k]:
            add("runnable", "changed", f"{k[0]}.{k[1]}", f"period: {ra[k]} -> {rb[k]}")

    da = {(d["from"], d["to"]) for d in old.dependencies}
    db = {(d["from"], d["to"]) for d in new.dependencies}
    for f, t in sorted(db - da):
        add("dependency", "added", f"{f} -> {t}")
    for f, t in sorted(da - db):
        add("dependency", "removed", f"{f} -> {t}")
    return rows
