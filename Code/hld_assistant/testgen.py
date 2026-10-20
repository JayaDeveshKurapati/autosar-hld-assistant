"""Test-case skeleton generation. Every case traces to an extracted entity and its source location."""
from __future__ import annotations

from .extract import Extraction
from .impact import period_ms

INT_RANGES = {"uint8": (0, 255), "uint16": (0, 65535), "uint32": (0, 4294967295), "sint8": (-128, 127),
              "sint16": (-32768, 32767), "sint32": (-2147483648, 2147483647), "boolean": (0, 1)}
COLUMNS = ["id", "type", "priority", "title", "preconditions", "steps", "expected", "trace_to", "page", "section"]


def generate(ex: Extraction, reqs: list[dict]) -> list[dict]:
    cases: list[dict] = []

    def add(type_, prio, title, steps, expected, trace, page, section, pre="ECU powered, software initialised"):
        cases.append({"id": f"TC-{len(cases) + 1:03d}", "type": type_, "priority": prio, "title": title,
                      "preconditions": pre, "steps": steps, "expected": expected, "trace_to": trace,
                      "page": page, "section": section})

    ports = {(p.component, p.name): p for p in ex.ports}
    for c in ex.connections:
        s, d = f"{c['from_comp']}.{c['from_port']}", f"{c['to_comp']}.{c['to_port']}"
        p = ports.get((c["from_comp"], c["from_port"]))
        sig = p.signal if p and p.signal else "the data element"
        add("functional", "high", f"Signal propagation {s} -> {d}",
            f"1. Stimulate {c['from_comp']} so it writes {sig} on {c['from_port']}. 2. Observe {d}.",
            f"{c['to_comp']} receives the value written by {c['from_comp']} unchanged.", f"{s} -> {d}",
            c["page"], c["section"])
        add("negative", "medium", f"Provider silent on {s}",
            f"1. Suppress updates from {c['from_comp']}. 2. Run {c['to_comp']} for several periods.",
            f"{c['to_comp']} detects the missing update / uses the specified default; no undefined behaviour.",
            f"{s} -> {d}", c["page"], c["section"])

    for p in ex.ports:
        if p.direction in ("P", "PR") and p.dtype:
            rng = INT_RANGES.get(p.dtype.lower())
            trace = f"{p.component}.{p.name}"
            if rng:
                add("boundary", "medium", f"Boundary values on {trace} ({p.dtype})",
                    f"1. Drive {p.signal or p.name} to {rng[0]}, {rng[1]}, and just outside the range. 2. Observe the consumer.",
                    "In-range values pass unchanged; out-of-range handling follows the specification.",
                    trace, p.page, p.section)
            elif p.dtype.lower().startswith("float"):
                add("boundary", "medium", f"Float edge cases on {trace} ({p.dtype})",
                    f"1. Drive {p.signal or p.name} with 0, min/max range, NaN and Inf. 2. Observe the consumer.",
                    "Valid values pass unchanged; NaN/Inf are rejected or limited per specification.",
                    trace, p.page, p.section)

    for r in ex.runnables:
        if (ms := period_ms(r["period"])) is not None:
            add("timing", "medium", f"Activation period of {r['component']}.{r['name']}",
                f"1. Trace {r['name']} start times over 1000 activations.",
                f"Mean period {ms:g} ms within the allowed jitter; no missed activations.",
                f"{r['component']}.{r['name']}", r["page"], r["section"])

    for q in reqs:
        trace = q["id"]
        if q["kind"] == "timing" and q["limit_ms"] is not None:
            add("timing", "high", f"Verify {q['id']}: end-to-end timing", "1. Inject the stimulus and timestamp the response at the output.",
                f"Measured latency <= {q['limit_ms']:g} ms in all runs. ({q['text']})", trace, q["page"], q["section"])
        elif q["kind"] == "safety":
            add("robustness", "high", f"Verify {q['id']}: fault reaction", "1. Inject the fault described in the requirement. 2. Observe the reaction.",
                f"System reaction matches: {q['text']}", trace, q["page"], q["section"])
        else:
            add("functional", "medium", f"Verify {q['id']}", "1. Create the conditions described. 2. Observe the behaviour.",
                f"Behaviour matches: {q['text']}", trace, q["page"], q["section"])
    return cases
