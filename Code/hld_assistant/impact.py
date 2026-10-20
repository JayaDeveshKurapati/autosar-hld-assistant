"""Graph analysis: change-impact, end-to-end chains with a latency estimate, dependency cycles."""
from __future__ import annotations

import re
from collections import defaultdict, deque

from .extract import Extraction

_UNIT = {"s": 1000.0, "ms": 1.0, "us": 0.001}


def period_ms(text: str | None) -> float | None:
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(ms|us|s)\b", text or "", re.I)
    return float(m.group(1)) * _UNIT[m.group(2).lower()] if m else None


def component_periods(ex: Extraction) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for r in ex.runnables:
        if (p := period_ms(r["period"])) is not None:
            out[r["component"]].append(p)
    return out


def flow_edges(ex: Extraction, include_dependencies: bool = True) -> list[tuple[str, str, str]]:
    """Data-flow edges (provider -> consumer, label). A declared dependency 'A depends on B' is B -> A."""
    ports = {(p.component, p.name): p for p in ex.ports}
    edges: dict[tuple[str, str], str] = {}
    for c in ex.connections:
        p = ports.get((c["from_comp"], c["from_port"]))
        edges[(c["from_comp"], c["to_comp"])] = (p.signal or p.interface or c["from_port"]) if p else c["from_port"]
    if include_dependencies:
        for d in ex.dependencies:
            edges.setdefault((d["to"], d["from"]), "depends")
    return [(a, b, label) for (a, b), label in edges.items()]


def _bfs(adj: dict[str, list[str]], seeds: list[str]) -> list[dict]:
    seen = {s: [s] for s in seeds}
    q, out = deque(seeds), []
    while q:
        n = q.popleft()
        for m in adj.get(n, []):
            if m not in seen:
                seen[m] = seen[n] + [m]
                out.append({"component": m, "depth": len(seen[m]) - 1, "path": " -> ".join(seen[m])})
                q.append(m)
    return out


def impact(ex: Extraction, kind: str, name: str) -> dict:
    """What is affected if a component / signal / interface changes."""
    if kind == "component":
        seeds = [name] if name in ex.components else []
    elif kind == "signal":
        seeds = sorted({p.component for p in ex.ports if p.signal == name})
    elif kind == "interface":
        seeds = sorted({p.component for p in ex.ports if p.interface == name})
    else:
        raise ValueError("kind must be component, signal or interface")
    fwd, rev = defaultdict(list), defaultdict(list)
    for a, b, _ in flow_edges(ex):
        fwd[a].append(b)
        rev[b].append(a)
    down = [d for d in _bfs(fwd, seeds) if d["component"] not in seeds]
    up = [d for d in _bfs(rev, seeds) if d["component"] not in seeds]
    return {"kind": kind, "target": name, "found": bool(seeds), "directly_affected": seeds,
            "downstream": down, "upstream": up}


def chains(ex: Extraction, limit: int = 200) -> list[dict]:
    """Source-to-sink paths over port connections. Latency is a coarse worst-case estimate:
    each component contributes its slowest runnable period (sampling delay); execution and
    communication time are ignored, components without a period are listed as unknown."""
    adj: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = defaultdict(int)
    for a, b, _ in flow_edges(ex, include_dependencies=False):
        adj[a].append(b)
        indeg[b] += 1
    periods = component_periods(ex)
    result: list[dict] = []

    def dfs(node: str, path: list[str]):
        if len(result) >= limit:
            return
        nxt = [m for m in adj.get(node, []) if m not in path]
        if not nxt:
            if len(path) > 1:
                known = [max(periods[c]) for c in path if c in periods]
                result.append({"path": path, "latency_ms": sum(known),
                               "unknown": [c for c in path if c not in periods]})
            return
        for m in nxt:
            dfs(m, path + [m])

    for s in sorted(n for n in adj if indeg[n] == 0):
        dfs(s, [s])
    return sorted(result, key=lambda c: -c["latency_ms"])


def find_cycles(ex: Extraction) -> list[list[str]]:
    """Dependency cycles (declared dependencies plus connections), each reported once."""
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b, _ in flow_edges(ex):
        adj[a].append(b)
    cycles: list[list[str]] = []
    seen_keys: set[frozenset] = set()
    state: dict[str, int] = {}

    def dfs(n: str, stack: list[str]):
        state[n] = 1
        stack.append(n)
        for m in adj.get(n, []):
            if state.get(m) == 1:
                cyc = stack[stack.index(m):]
                if (key := frozenset(cyc)) not in seen_keys:
                    seen_keys.add(key)
                    cycles.append(cyc + [m])
            elif m not in state:
                dfs(m, stack)
        stack.pop()
        state[n] = 2

    for n in sorted(adj):
        if n not in state:
            dfs(n, [])
    return cycles
