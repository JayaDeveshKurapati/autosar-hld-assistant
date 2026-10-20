"""Deterministic, fully cited reports derived from the extraction (no LLM involved)."""
from __future__ import annotations

from .extract import Extraction


def component_report(ex: Extraction, name: str) -> dict | None:
    comp = ex.components.get(name)
    if comp is None:
        return None
    ports = [p for p in ex.ports if p.component == name]
    conns_out = [c for c in ex.connections if c["from_comp"] == name]
    conns_in = [c for c in ex.connections if c["to_comp"] == name]
    return {
        "component": name,
        "kind": comp["kind"],
        "source": {"page": comp["page"], "section": comp["section"]},
        "ports": [vars(p) for p in ports],
        "runnables": [r for r in ex.runnables if r["component"] == name],
        "depends_on": [d for d in ex.dependencies if d["from"] == name],
        "depended_on_by": [d for d in ex.dependencies if d["to"] == name],
        "outgoing": conns_out,
        "incoming": conns_in,
    }


def signal_trace(ex: Extraction, signal: str) -> dict:
    """Who provides and who requires a signal, per ports + connections."""
    sig_ports = [p for p in ex.ports if p.signal == signal]
    return {
        "signal": signal,
        "definition": ex.signals.get(signal),
        "providers": [vars(p) for p in sig_ports if p.direction in ("P", "PR")],
        "consumers": [vars(p) for p in sig_ports if p.direction in ("R", "PR")],
    }


def dependency_edges(ex: Extraction) -> list[tuple[str, str, str]]:
    """(from, to, label) edges from declared deps and port connections, de-duplicated."""
    edges = {(d["from"], d["to"], "depends") for d in ex.dependencies}
    ports = {(p.component, p.name): p for p in ex.ports}
    for c in ex.connections:
        p = ports.get((c["from_comp"], c["from_port"]))
        label = (p.signal or p.interface or c["from_port"]) if p else c["from_port"]
        edges.add((c["from_comp"], c["to_comp"], label))
    return sorted(edges)


def dependency_dot(ex: Extraction) -> str:
    lines = ["digraph HLD {", "  rankdir=LR;", "  node [shape=box, style=rounded];"]
    for name in ex.components:
        lines.append(f'  "{name}";')
    for a, b, label in dependency_edges(ex):
        style = ' style=dashed' if label == "depends" else ""
        lines.append(f'  "{a}" -> "{b}" [label="{label if label != "depends" else ""}"{style}];')
    lines.append("}")
    return "\n".join(lines)
