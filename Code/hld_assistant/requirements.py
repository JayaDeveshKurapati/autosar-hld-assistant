"""Requirement ("shall") extraction, entity traceability and timing-budget checks."""
from __future__ import annotations

import hashlib
import re

from .checks import _finding
from .extract import Extraction
from .impact import chains, period_ms
from .ingest import HEADING_RE, Chunk

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")
MODAL = re.compile(r"\b(shall|must)\b", re.I)
EXPLICIT_ID = re.compile(r"^\[?((?:REQ|HLD|SW|SYS|FSR|TSR)[-_][A-Za-z0-9_.-]+)\]?[:\s]+")
LIMIT = re.compile(r"(?:not exceed|within|at most|less than|below|no more than|maximum of|<=?)\s*"
                   r"(\d+(?:\.\d+)?\s*(?:ms|us|s))\b", re.I)
TIMING_WORDS = re.compile(r"\b(latency|period|deadline|timeout|response time|delay|jitter)\b", re.I)
SAFETY_WORDS = re.compile(r"\b(degraded|fail\w*|safe state|plausib\w*|fault|diagnos\w*|limit\w*)\b", re.I)


def extract_requirements(chunks: list[Chunk], ex: Extraction) -> list[dict]:
    names = ({n: "component" for n in ex.components} | {n: "interface" for n in ex.interfaces}
             | {s: "signal" for s in {p.signal for p in ex.ports if p.signal} | set(ex.signals)})
    reqs, seen = [], set()
    for ch in chunks:
        body = " ".join(ln.strip() for ln in ch.text.splitlines() if ln.strip() and not HEADING_RE.match(ln.strip()))
        for sent in SENTENCE_SPLIT.split(body):
            sent = sent.strip()
            if not MODAL.search(sent):
                continue
            explicit = EXPLICIT_ID.match(sent)
            rid = explicit.group(1) if explicit else "R-" + hashlib.sha1(sent.encode()).hexdigest()[:6]
            if rid in seen:
                continue
            seen.add(rid)
            limit = LIMIT.search(sent)
            kind = "timing" if (limit or TIMING_WORDS.search(sent)) else "safety" if SAFETY_WORDS.search(sent) else "functional"
            reqs.append({"id": rid, "text": sent, "kind": kind, "page": ch.page, "section": ch.section,
                         "limit_ms": period_ms(limit.group(1)) if limit else None,
                         "entities": [{"name": n, "type": t} for n, t in names.items()
                                      if re.search(rf"\b{re.escape(n)}\b", sent)]})
    return reqs


def requirement_findings(ex: Extraction, reqs: list[dict]) -> list[dict]:
    out = []
    for r in reqs:
        if not r["entities"]:
            out.append(_finding("REQUIREMENT_UNTRACED", "info",
                                f"Requirement {r['id']} references no known component, interface or signal.",
                                r["page"], r["section"], r["text"]))
    chain_list = chains(ex)
    for r in (r for r in reqs if r["limit_ms"] is not None and chain_list):
        scoped = {e["name"] for e in r["entities"] if e["type"] == "component"}
        pool = [c for c in chain_list if scoped & set(c["path"])] if scoped else chain_list[:1]
        if not pool:
            continue
        worst = max(pool, key=lambda c: c["latency_ms"])
        if worst["latency_ms"] > r["limit_ms"]:
            note = "" if scoped else " (requirement is not tied to a component, so the longest chain was used)"
            out.append(_finding(
                "TIMING_BUDGET_EXCEEDED", "warning" if scoped else "info",
                f"Requirement {r['id']} allows {r['limit_ms']:g} ms but chain {' -> '.join(worst['path'])} "
                f"has an estimated worst-case sampling latency of {worst['latency_ms']:g} ms{note}.",
                r["page"], r["section"], r["text"]))
    return out
