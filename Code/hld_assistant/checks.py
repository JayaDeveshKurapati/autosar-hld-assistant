"""Consistency / completeness checks over an Extraction.

Each finding is a candidate for engineer review - never an automatic verdict.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .extract import Extraction
from .impact import component_periods, find_cycles


def _finding(rule: str, severity: str, message: str, page: int, section: str, evidence: str) -> dict:
    fid = hashlib.sha1(f"{rule}|{message}".encode()).hexdigest()[:10]
    return {"id": fid, "rule": rule, "severity": severity, "message": message,
            "page": page, "section": section, "evidence": evidence}


def _canon(name: str) -> str:
    return re.sub(r"[_\s]", "", name).lower()


def run_checks(ex: Extraction) -> list[dict]:
    out: list[dict] = []
    ports = {(p.component, p.name): p for p in ex.ports}

    # Undefined interface references
    for p in ex.ports:
        if p.interface and p.interface not in ex.interfaces:
            out.append(_finding("UNDEFINED_INTERFACE", "error",
                                f"Port {p.component}.{p.name} uses interface '{p.interface}' which is not defined in the document.",
                                p.page, p.section, p.evidence))
        if not p.interface:
            out.append(_finding("PORT_WITHOUT_INTERFACE", "warning",
                                f"Port {p.component}.{p.name} does not name an interface.", p.page, p.section, p.evidence))

    # Undefined components in dependencies / connections
    for d in ex.dependencies:
        if d["to"] not in ex.components:
            out.append(_finding("UNDEFINED_COMPONENT", "error",
                                f"{d['from']} depends on '{d['to']}' which has no component description.",
                                d["page"], d["section"], d["evidence"]))
    for c in ex.connections:
        for side in ("from", "to"):
            comp, port = c[f"{side}_comp"], c[f"{side}_port"]
            if comp not in ex.components:
                out.append(_finding("UNDEFINED_COMPONENT", "error",
                                    f"Connection references unknown component '{comp}'.", c["page"], c["section"], c["evidence"]))
            elif (comp, port) not in ports:
                out.append(_finding("UNDEFINED_PORT", "error",
                                    f"Connection references port '{comp}.{port}' which is not declared.",
                                    c["page"], c["section"], c["evidence"]))

    # Connection direction + interface compatibility
    connected_out, connected_in = set(), set()
    for c in ex.connections:
        src, dst = ports.get((c["from_comp"], c["from_port"])), ports.get((c["to_comp"], c["to_port"]))
        connected_out.add((c["from_comp"], c["from_port"]))
        connected_in.add((c["to_comp"], c["to_port"]))
        if src and src.direction == "R":
            out.append(_finding("WRONG_DIRECTION", "error",
                                f"Connection starts at require-port {src.component}.{src.name}; providers must be P-ports.",
                                c["page"], c["section"], c["evidence"]))
        if dst and dst.direction == "P":
            out.append(_finding("WRONG_DIRECTION", "error",
                                f"Connection ends at provide-port {dst.component}.{dst.name}; receivers must be R-ports.",
                                c["page"], c["section"], c["evidence"]))
        if src and dst and src.interface and dst.interface and src.interface != dst.interface:
            out.append(_finding("INTERFACE_MISMATCH", "error",
                                f"{src.component}.{src.name} ({src.interface}) is connected to {dst.component}.{dst.name} ({dst.interface}).",
                                c["page"], c["section"], c["evidence"]))
        if src and dst and src.dtype and dst.dtype and src.dtype != dst.dtype:
            out.append(_finding("DATATYPE_MISMATCH", "error",
                                f"Connected ports differ in data type: {src.component}.{src.name} is {src.dtype}, "
                                f"{dst.component}.{dst.name} is {dst.dtype}.", c["page"], c["section"], c["evidence"]))

    # Unconnected ports (only meaningful when the doc describes connections at all)
    if ex.connections:
        for p in ex.ports:
            key = (p.component, p.name)
            if p.direction == "R" and key not in connected_in:
                out.append(_finding("UNCONNECTED_REQUIRE_PORT", "warning",
                                    f"Require-port {p.component}.{p.name} has no provider connection (missing dependency?).",
                                    p.page, p.section, p.evidence))
            if p.direction == "P" and key not in connected_out:
                out.append(_finding("UNCONNECTED_PROVIDE_PORT", "info",
                                    f"Provide-port {p.component}.{p.name} is not consumed by any connection.",
                                    p.page, p.section, p.evidence))

    # Declared dependency without any connection between the two components
    linked = {frozenset((c["from_comp"], c["to_comp"])) for c in ex.connections}
    if ex.connections:
        for d in ex.dependencies:
            if d["to"] in ex.components and frozenset((d["from"], d["to"])) not in linked:
                out.append(_finding("DEPENDENCY_WITHOUT_CONNECTION", "warning",
                                    f"{d['from']} declares a dependency on {d['to']} but no port connection links them.",
                                    d["page"], d["section"], d["evidence"]))

    # Same signal, different data types (or differing from the signal dictionary)
    types: dict[str, set[str]] = defaultdict(set)
    first: dict[str, object] = {}
    for p in ex.ports:
        if p.signal and p.dtype:
            types[p.signal].add(p.dtype)
            first.setdefault(p.signal, p)
    for sig, ts in types.items():
        dict_t = ex.signals.get(sig, {}).get("type")
        all_t = ts | ({dict_t} if dict_t else set())
        if len(all_t) > 1:
            p = first[sig]
            out.append(_finding("SIGNAL_TYPE_CONFLICT", "error",
                                f"Signal '{sig}' is specified with conflicting types: {', '.join(sorted(all_t))}.",
                                p.page, p.section, p.evidence))

    # Terminology: identifiers that differ only by case / underscores
    names: dict[str, set[str]] = defaultdict(set)
    for n in list(ex.components) + list(ex.interfaces) + [p.signal for p in ex.ports if p.signal] + list(ex.signals):
        names[_canon(n)].add(n)
    for variants in names.values():
        if len(variants) > 1:
            out.append(_finding("TERMINOLOGY", "warning",
                                f"Inconsistent naming for the same identifier: {', '.join(sorted(variants))}.", 0, "-", ""))

    # Components without behaviour
    with_run = {r["component"] for r in ex.runnables}
    for name, c in ex.components.items():
        if name not in with_run:
            out.append(_finding("NO_RUNNABLE", "info", f"Component {name} has no runnable described.",
                                c["page"], c["section"], c["evidence"]))

    # Duplicate port names within one component
    seen_ports: set[tuple[str, str]] = set()
    for p in ex.ports:
        if (p.component, p.name) in seen_ports:
            out.append(_finding("DUPLICATE_PORT", "error", f"Port {p.component}.{p.name} is declared more than once.",
                                p.page, p.section, p.evidence))
        seen_ports.add((p.component, p.name))

    # Dependency cycles
    for cyc in find_cycles(ex):
        out.append(_finding("DEPENDENCY_CYCLE", "warning", f"Dependency cycle: {' -> '.join(cyc)}.", 0, "-", ""))

    # Producer / consumer rate mismatch on connections (sampling issues, not necessarily defects)
    periods = component_periods(ex)
    for c in ex.connections:
        a, b = periods.get(c["from_comp"]), periods.get(c["to_comp"])
        if a and b and min(a) != min(b):
            slow, fast = (("consumer", "producer") if min(b) > min(a) else ("producer", "consumer"))
            note = "samples may be dropped" if slow == "consumer" else "the consumer may read stale data"
            out.append(_finding("RATE_MISMATCH", "info",
                                f"{c['from_comp']} runs every {min(a):g} ms but {c['to_comp']} every {min(b):g} ms "
                                f"({slow} is slower; {note}).", c["page"], c["section"], c["evidence"]))

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda f: (order[f["severity"]], f["rule"], f["message"]))
    return out
