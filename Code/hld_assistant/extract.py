"""Rule-based architecture entity extraction.

Deterministic on purpose: every entity carries page/section/evidence so reviewers can
verify it. An LLM extractor can be layered on top and merged into the same schema.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ingest import Chunk

NAME = r"[A-Za-z_][A-Za-z0-9_]*"
BULLET = r"^[-*•\s]*"

COMPONENT_HDR = re.compile(rf"^\d+(?:\.\d+)*\.?\s+({NAME})\s*\((\w*SwComponentType|Composition|ComplexDeviceDriver)\)", re.I)
INTERFACE_HDR = re.compile(rf"^\d+(?:\.\d+)*\.?\s+({NAME})\s*\((SenderReceiver|ClientServer|ModeSwitch|NvData|Parameter)\s*Interface\)", re.I)
PORT = re.compile(rf"{BULLET}(PR|P|R)[- ]?Port\s+({NAME})\s*:\s*(.*)$", re.I)
KV_INTERFACE = re.compile(rf"interface\s+({NAME})", re.I)
KV_SIGNAL = re.compile(rf"signal\s+({NAME})", re.I)
KV_TYPE = re.compile(rf"type\s+({NAME})", re.I)
RUNNABLE = re.compile(rf"\b(Run_{NAME})(?:\s*\(\s*(?:period\s+)?([\w .]+?)\s*\))?")
DEPENDS = re.compile(r"^(?:Depends on|Requires|Uses)\s*:\s*(.+)$", re.I)
CONNECTION = re.compile(rf"\b({NAME})\.({NAME})\s*(?:->|→|=>)\s*({NAME})\.({NAME})")
ELEMENT = re.compile(rf"{BULLET}(?:Data element|Element|Operation)\s+({NAME})\s*:\s*(\w+)", re.I)
SIGNAL_DEF = re.compile(rf"{BULLET}Signal\s+({NAME})\s*:\s*(\w+)(?:.*?\bunit\s+([\w/%]+))?", re.I)


@dataclass
class Port:
    component: str
    name: str
    direction: str  # P / R / PR
    interface: str | None
    signal: str | None
    dtype: str | None
    page: int
    section: str
    evidence: str


@dataclass
class Extraction:
    components: dict[str, dict] = field(default_factory=dict)
    interfaces: dict[str, dict] = field(default_factory=dict)
    ports: list[Port] = field(default_factory=list)
    signals: dict[str, dict] = field(default_factory=dict)  # signal dictionary entries
    runnables: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    connections: list[dict] = field(default_factory=list)


def extract(chunks: list[Chunk]) -> Extraction:
    ex = Extraction()
    comp: str | None = None
    iface: str | None = None

    for ch in chunks:
        src = {"page": ch.page, "section": ch.section}
        lines = [ln.strip() for ln in ch.text.splitlines() if ln.strip()]
        if not lines:
            continue
        if m := COMPONENT_HDR.match(lines[0]):
            comp, iface = m.group(1), None
            ex.components.setdefault(comp, {"kind": m.group(2), **src, "evidence": lines[0]})
        elif m := INTERFACE_HDR.match(lines[0]):
            iface, comp = m.group(1), None
            ex.interfaces.setdefault(iface, {"kind": m.group(2), "elements": {}, **src, "evidence": lines[0]})
        elif re.match(r"^\d+(?:\.\d+)*\.?\s+", lines[0]):
            comp = iface = None  # an unrelated heading ends the component/interface context

        for line in lines:
            if m := PORT.match(line):
                if comp:
                    rest = m.group(3)
                    i, s, t = KV_INTERFACE.search(rest), KV_SIGNAL.search(rest), KV_TYPE.search(rest)
                    ex.ports.append(Port(comp, m.group(2), m.group(1).upper(), i and i.group(1),
                                         s and s.group(1), t and t.group(1), ch.page, ch.section, line))
                continue
            if m := ELEMENT.match(line):
                if iface:
                    ex.interfaces[iface]["elements"][m.group(1)] = m.group(2)
                continue
            if m := SIGNAL_DEF.match(line):
                ex.signals.setdefault(m.group(1), {"type": m.group(2), "unit": m.group(3), **src, "evidence": line})
                continue
            if m := DEPENDS.match(line):
                if comp:
                    for dep in re.split(r"[,;]\s*", m.group(1).rstrip(".")):
                        if dep.strip():
                            ex.dependencies.append({"from": comp, "to": dep.strip(), **src, "evidence": line})
                continue
            for mc in CONNECTION.finditer(line):
                ex.connections.append({"from_comp": mc.group(1), "from_port": mc.group(2),
                                       "to_comp": mc.group(3), "to_port": mc.group(4), **src, "evidence": line})
            if comp:
                for mr in RUNNABLE.finditer(line):
                    ex.runnables.append({"component": comp, "name": mr.group(1), "period": mr.group(2), **src, "evidence": line})

    seen, uniq = set(), []
    for r in ex.runnables:
        if (r["component"], r["name"]) not in seen:
            seen.add((r["component"], r["name"]))
            uniq.append(r)
    ex.runnables = uniq
    return ex
