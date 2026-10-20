"""ARXML import: builds the same Extraction schema as the text extractor, straight from the model.

Covers the parts relevant to HLD analysis: port interfaces (S/R, C/S, mode, NV, parameter),
software component types, ports, runnables with timing-event periods, and assembly connectors
inside compositions (prototype names are resolved back to component type names).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .extract import Extraction, Port
from .ingest import Chunk

INTERFACE_KINDS = {
    "SENDER-RECEIVER-INTERFACE": "SenderReceiver",
    "CLIENT-SERVER-INTERFACE": "ClientServer",
    "MODE-SWITCH-INTERFACE": "ModeSwitch",
    "NV-DATA-INTERFACE": "NvData",
    "PARAMETER-INTERFACE": "Parameter",
}
PORT_TAGS = {"P-PORT-PROTOTYPE": "P", "R-PORT-PROTOTYPE": "R", "PR-PORT-PROTOTYPE": "PR"}
PORT_REF_TAGS = ("PROVIDED-INTERFACE-TREF", "REQUIRED-INTERFACE-TREF", "PROVIDED-REQUIRED-INTERFACE-TREF")


def _t(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _kids(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _t(c) == name]


def _kid(el: ET.Element, name: str) -> ET.Element | None:
    k = _kids(el, name)
    return k[0] if k else None


def _txt(el: ET.Element, name: str) -> str | None:
    k = _kid(el, name)
    return k.text.strip() if k is not None and k.text else None


def _last(ref: ET.Element | None) -> str | None:
    return ref.text.strip().rsplit("/", 1)[-1] if ref is not None and ref.text else None


def _fmt_period(seconds: str | None) -> str | None:
    try:
        return f"{round(float(seconds) * 1000, 3):g} ms"
    except (TypeError, ValueError):
        return None


def _walk_packages(el: ET.Element, path: str = ""):
    """Yield (path, element) for every element held in an AR-PACKAGE's ELEMENTS."""
    for pk in _kids(el, "AR-PACKAGES"):
        for pkg in _kids(pk, "AR-PACKAGE"):
            p = f"{path}/{_txt(pkg, 'SHORT-NAME')}"
            for elems in _kids(pkg, "ELEMENTS"):
                for e in elems:
                    yield p, e
            yield from _walk_packages(pkg, p)


def parse_arxml(data: bytes) -> tuple[list[Chunk], Extraction]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"Invalid ARXML: {e}") from e

    ex = Extraction()
    items = list(_walk_packages(root))

    for path, e in items:
        tag = _t(e)
        if tag in INTERFACE_KINDS:
            name = _txt(e, "SHORT-NAME")
            elements: dict[str, str] = {}
            for container, child in (("DATA-ELEMENTS", "VARIABLE-DATA-PROTOTYPE"),
                                     ("OPERATIONS", "CLIENT-SERVER-OPERATION"),
                                     ("NV-DATAS", "VARIABLE-DATA-PROTOTYPE"),
                                     ("PARAMETERS", "PARAMETER-DATA-PROTOTYPE")):
                for c in _kids(e, container):
                    for v in _kids(c, child):
                        elements[_txt(v, "SHORT-NAME") or "?"] = _last(_kid(v, "TYPE-TREF")) or "operation"
            ex.interfaces[name] = {"kind": INTERFACE_KINDS[tag], "elements": elements, "page": 1,
                                   "section": f"ARXML {path}/{name}", "evidence": f"<{tag}> {name}"}

    prototypes: dict[tuple[str, str], str] = {}  # (composition, prototype) -> type name
    compositions: list[tuple[str, ET.Element]] = []

    for path, e in items:
        tag = _t(e)
        if not tag.endswith("SW-COMPONENT-TYPE"):
            continue
        name = _txt(e, "SHORT-NAME")
        kind = "".join(w.capitalize() for w in tag.split("-"))
        section = f"ARXML {path}/{name}"
        ex.components[name] = {"kind": kind, "page": 1, "section": section, "evidence": f"<{tag}> {name}"}
        for ports in _kids(e, "PORTS"):
            for p in ports:
                if _t(p) not in PORT_TAGS:
                    continue
                iref = next((_last(_kid(p, r)) for r in PORT_REF_TAGS if _kid(p, r) is not None), None)
                elems = ex.interfaces.get(iref, {}).get("elements", {})
                sig, dtype = next(iter(elems.items()), (None, None))
                if dtype == "operation":
                    sig = dtype = None
                ex.ports.append(Port(name, _txt(p, "SHORT-NAME"), PORT_TAGS[_t(p)], iref, sig, dtype, 1,
                                     section, f"<{_t(p)}> {_txt(p, 'SHORT-NAME')}"))
        for ib in _kids(e, "INTERNAL-BEHAVIORS"):
            for beh in _kids(ib, "SWC-INTERNAL-BEHAVIOR"):
                periods: dict[str, str | None] = {}
                for evs in _kids(beh, "EVENTS"):
                    for ev in _kids(evs, "TIMING-EVENT"):
                        periods[_last(_kid(ev, "START-ON-EVENT-REF"))] = _fmt_period(_txt(ev, "PERIOD"))
                for runs in _kids(beh, "RUNNABLES"):
                    for r in _kids(runs, "RUNNABLE-ENTITY"):
                        rn = _txt(r, "SHORT-NAME")
                        ex.runnables.append({"component": name, "name": rn, "period": periods.get(rn), "page": 1,
                                             "section": section, "evidence": f"<RUNNABLE-ENTITY> {rn}"})
        if tag == "COMPOSITION-SW-COMPONENT-TYPE":
            compositions.append((name, e))
            for comps in _kids(e, "COMPONENTS"):
                for proto in _kids(comps, "SW-COMPONENT-PROTOTYPE"):
                    prototypes[(name, _txt(proto, "SHORT-NAME"))] = _last(_kid(proto, "TYPE-TREF"))

    for comp_name, e in compositions:
        section = ex.components[comp_name]["section"]
        for conns in _kids(e, "CONNECTORS"):
            for c in _kids(conns, "ASSEMBLY-SW-CONNECTOR"):
                prov, req = _kid(c, "PROVIDER-IREF"), _kid(c, "REQUESTER-IREF")
                if prov is None or req is None:
                    continue
                pc = prototypes.get((comp_name, _last(_kid(prov, "CONTEXT-COMPONENT-REF"))))
                rc = prototypes.get((comp_name, _last(_kid(req, "CONTEXT-COMPONENT-REF"))))
                pp = _last(_kid(prov, "TARGET-P-PORT-REF")) or _last(_kid(prov, "TARGET-PR-PORT-REF"))
                rp = _last(_kid(req, "TARGET-R-PORT-REF")) or _last(_kid(req, "TARGET-PR-PORT-REF"))
                ex.connections.append({"from_comp": pc, "from_port": pp, "to_comp": rc, "to_port": rp, "page": 1,
                                       "section": section, "evidence": f"<ASSEMBLY-SW-CONNECTOR> {_txt(c, 'SHORT-NAME')}"})
    return _synthesize_chunks(ex), ex


def _synthesize_chunks(ex: Extraction) -> list[Chunk]:
    """Readable text per interface/component so the same search and Q&A works on ARXML."""
    chunks = []
    for n, i in ex.interfaces.items():
        body = "\n".join(f"- Data element {k}: {v}" for k, v in i["elements"].items())
        chunks.append(Chunk(1, i["section"], f"{n} ({i['kind']} Interface)\n{body}"))
    for n, c in ex.components.items():
        lines = [f"{n} ({c['kind']})"]
        lines += [f"- {p.direction}-Port {p.name}: interface {p.interface}"
                  + (f", signal {p.signal}, type {p.dtype}" if p.signal else "") for p in ex.ports if p.component == n]
        lines += [f"Runnable {r['name']}" + (f" (period {r['period']})" if r["period"] else "")
                  for r in ex.runnables if r["component"] == n]
        lines += [f"{x['from_comp']}.{x['from_port']} -> {x['to_comp']}.{x['to_port']}"
                  for x in ex.connections if n in (x["from_comp"], x["to_comp"])]
        chunks.append(Chunk(1, c["section"], "\n".join(lines)))
    return chunks
