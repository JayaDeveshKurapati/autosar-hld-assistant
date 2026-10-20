"""Application service: the one place that wires ingestion, storage, analysis, Q&A and export."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import asdict

from . import arxml, checks, compare, impact, ingest, qa, reportgen, reports, requirements, testgen
from .extract import Extraction, extract
from .store import Store

STATUSES = {"draft", "in_review", "approved"}


def _csv(rows: list[dict], cols: list[str]) -> str:
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return s.getvalue()


class Service:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    # ---- ingestion -------------------------------------------------------
    def ingest(self, project: str, name: str, data: bytes, version: str = "1.0",
               status: str = "draft", actor: str = "anonymous") -> dict:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)}")
        if name.lower().endswith((".arxml", ".xml")):
            chunks, ex = arxml.parse_arxml(data)
            n_pages = 1
        else:
            pages = ingest.load_pages(name, data)
            chunks = ingest.chunk_pages(pages)
            ex, n_pages = extract(chunks), len(pages)
        doc_id = self.store.add_document(project, name, version, status, n_pages, chunks, ex)
        self.store.audit(actor, "ingest", f"{project}/{name} v{version} -> doc {doc_id}")
        return {"doc_id": doc_id, "pages": n_pages, "chunks": len(chunks), **self.summary(doc_id)}

    def _doc(self, doc_id: int) -> dict:
        d = self.store.get_document(doc_id)
        if d is None:
            raise KeyError(f"document {doc_id} not found")
        return d

    def summary(self, doc_id: int) -> dict:
        ex = self._doc(doc_id)["extraction"]
        return {"components": len(ex.components), "interfaces": len(ex.interfaces), "ports": len(ex.ports),
                "connections": len(ex.connections), "runnables": len(ex.runnables),
                "dependencies": len(ex.dependencies)}

    # ---- analysis --------------------------------------------------------
    def extraction(self, doc_id: int) -> Extraction:
        return self._doc(doc_id)["extraction"]

    def requirements(self, doc_id: int) -> list[dict]:
        d = self._doc(doc_id)
        return requirements.extract_requirements(d["chunks"], d["extraction"])

    def findings(self, doc_id: int) -> list[dict]:
        d = self._doc(doc_id)
        ex = d["extraction"]
        reqs = requirements.extract_requirements(d["chunks"], ex)
        out = checks.run_checks(ex) + requirements.requirement_findings(ex, reqs)
        order = {"error": 0, "warning": 1, "info": 2}
        out.sort(key=lambda f: (order[f["severity"]], f["rule"], f["message"]))
        reviews = self.store.reviews(doc_id)
        for f in out:
            r = reviews.get(f["id"])
            f["review"] = {"decision": r["decision"], "note": r["note"], "reviewer": r["reviewer"]} if r else None
        return out

    def review_finding(self, doc_id: int, finding_id: str, decision: str, note: str = "", reviewer: str = "anonymous"):
        if decision not in {"confirmed", "dismissed", "open"}:
            raise ValueError("decision must be confirmed, dismissed or open")
        self.store.save_review(doc_id, finding_id, decision, note, reviewer)
        self.store.audit(reviewer, "review", f"doc {doc_id} finding {finding_id}: {decision}")

    def set_status(self, doc_id: int, status: str, actor: str = "anonymous") -> None:
        """Approval is gated: every error-level finding needs a confirmed/dismissed decision first."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {sorted(STATUSES)}")
        if status == "approved":
            pending = [f for f in self.findings(doc_id)
                       if f["severity"] == "error" and (not f["review"] or f["review"]["decision"] == "open")]
            if pending:
                raise ValueError(f"Cannot approve: {len(pending)} error finding(s) have no review decision yet.")
        self._doc(doc_id)
        self.store.set_status(doc_id, status)
        self.store.audit(actor, "status", f"doc {doc_id} -> {status}")

    def compare(self, old_id: int, new_id: int) -> list[dict]:
        return compare.compare(self.extraction(old_id), self.extraction(new_id))

    def text_diff(self, old_id: int, new_id: int) -> list[dict]:
        return compare.section_diff(self._doc(old_id)["chunks"], self._doc(new_id)["chunks"])

    def component_report(self, doc_id: int, name: str):
        return reports.component_report(self.extraction(doc_id), name)

    def signal_trace(self, doc_id: int, signal: str):
        return reports.signal_trace(self.extraction(doc_id), signal)

    def impact(self, doc_id: int, kind: str, name: str) -> dict:
        return impact.impact(self.extraction(doc_id), kind, name)

    def chains(self, doc_id: int) -> list[dict]:
        return impact.chains(self.extraction(doc_id))

    def test_plan(self, doc_id: int) -> list[dict]:
        return testgen.generate(self.extraction(doc_id), self.requirements(doc_id))

    # ---- Q&A -------------------------------------------------------------
    def _facts(self, question: str, doc: dict) -> list[dict]:
        """Deterministic facts about components / signals / interfaces named in the question."""
        ex, facts = doc["extraction"], []
        src = lambda x: {"doc": doc["name"], "version": doc["version"], "page": x["page"], "section": x["section"]}  # noqa: E731
        for name, c in ex.components.items():
            if re.search(rf"\b{re.escape(name)}\b", question):
                r = reports.component_report(ex, name)
                ports = "; ".join(f"{p['direction']}-port {p['name']} ({p['interface']})" for p in r["ports"]) or "no ports"
                runs = ", ".join(f"{x['name']} ({x['period'] or 'no period'})" for x in r["runnables"]) or "none"
                deps = ", ".join(d["to"] for d in r["depends_on"]) or "none"
                facts.append({"text": f"{name} is a {c['kind']} with {ports}. Runnables: {runs}. Depends on: {deps}.", **src(c)})
        signals = {p.signal for p in ex.ports if p.signal} | set(ex.signals)
        for s in sorted(signals):
            if re.search(rf"\b{re.escape(s)}\b", question):
                t = reports.signal_trace(ex, s)
                prov = ", ".join(f"{p['component']}.{p['name']}" for p in t["providers"]) or "none declared"
                cons = ", ".join(f"{p['component']}.{p['name']}" for p in t["consumers"]) or "none declared"
                first = (t["providers"] or t["consumers"] or [{"page": 0, "section": "-"}])[0]
                facts.append({"text": f"Signal {s}: provided by {prov}; consumed by {cons}.", **src(first)})
        for n, i in ex.interfaces.items():
            if re.search(rf"\b{re.escape(n)}\b", question):
                users = ", ".join(f"{p.component}.{p.name}" for p in ex.ports if p.interface == n) or "no ports"
                els = ", ".join(f"{k}: {v}" for k, v in i["elements"].items()) or "no elements"
                facts.append({"text": f"Interface {n} ({i['kind']}) carries {els}; used by {users}.", **src(i)})
        return facts

    def ask(self, question: str, doc_ids: list[int], actor: str = "anonymous") -> dict:
        items, facts = [], []
        for did in doc_ids:
            d = self._doc(did)
            items += [{"doc_id": did, "doc_name": d["name"], "version": d["version"], "status": d["status"],
                       "page": c.page, "section": c.section, "text": c.text} for c in d["chunks"]]
            facts += self._facts(question, d)
        result = qa.answer(question, qa.Retriever(items))
        result["facts"] = facts
        if result["mode"] == "declined" and facts:
            result.update(answer="\n".join(f"- {f['text']}" for f in facts), confidence="medium", mode="structured")
        self.store.audit(actor, "ask", f"{question!r} docs={doc_ids} conf={result['confidence']} "
                                       f"cited={len(result['citations']) + len(facts)}")
        return result

    # ---- metrics ---------------------------------------------------------
    def metrics(self, project: str) -> dict:
        docs = self.store.list_documents(project)
        sev = {"error": 0, "warning": 0, "info": 0}
        confirmed = dismissed = openn = 0
        req_total = req_traced = 0
        for d in docs:
            for f in self.findings(d["id"]):
                sev[f["severity"]] += 1
                dec = (f["review"] or {}).get("decision", "open")
                confirmed += dec == "confirmed"
                dismissed += dec == "dismissed"
                openn += dec == "open"
            reqs = self.requirements(d["id"])
            req_total += len(reqs)
            req_traced += sum(1 for r in reqs if r["entities"])
        asks = [a for a in self.store.audit_log(5000) if a["action"] == "ask"]
        answered = [a for a in asks if "conf=none" not in a["detail"]]
        grounded = [a for a in answered if not a["detail"].endswith("cited=0")]
        pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
        return {"documents": len(docs), "findings_by_severity": sev,
                "reviews": {"confirmed": confirmed, "dismissed": dismissed, "open": openn},
                "finding_precision_pct": pct(confirmed, confirmed + dismissed),
                "requirement_trace_pct": pct(req_traced, req_total), "requirements": req_total,
                "questions": len(asks), "answer_rate_pct": pct(len(answered), len(asks)),
                "groundedness_pct": pct(len(grounded), len(answered))}

    # ---- export ----------------------------------------------------------
    def report_html(self, doc_id: int) -> str:
        d = self._doc(doc_id)
        return reportgen.build(d, self.summary(doc_id), self.findings(doc_id), self.requirements(doc_id),
                               self.chains(doc_id), self.test_plan(doc_id))

    def export_zip(self, doc_id: int) -> bytes:
        d = self._doc(doc_id)
        ex = d["extraction"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("extraction.json", json.dumps(asdict(ex), indent=2))
            z.writestr("components.csv", _csv([{"name": n, **c} for n, c in ex.components.items()],
                                              ["name", "kind", "page", "section"]))
            z.writestr("ports.csv", _csv([asdict(p) for p in ex.ports],
                                         ["component", "name", "direction", "interface", "signal", "dtype", "page", "section"]))
            z.writestr("connections.csv", _csv(ex.connections, ["from_comp", "from_port", "to_comp", "to_port", "page", "section"]))
            z.writestr("dependencies.csv", _csv(ex.dependencies, ["from", "to", "page", "section"]))
            z.writestr("findings.csv", _csv(
                [{**f, "decision": (f["review"] or {}).get("decision", "open")} for f in self.findings(doc_id)],
                ["id", "severity", "rule", "message", "page", "section", "decision"]))
            z.writestr("requirements.csv", _csv(
                [{**r, "entities": ", ".join(e["name"] for e in r["entities"])} for r in self.requirements(doc_id)],
                ["id", "kind", "text", "limit_ms", "entities", "page", "section"]))
            z.writestr("tests.csv", _csv(self.test_plan(doc_id), testgen.COLUMNS))
            z.writestr("dependencies.dot", reports.dependency_dot(ex))
            z.writestr("review_report.html", self.report_html(doc_id))
            z.writestr("README.txt", f"Source: {d['name']} v{d['version']} (status: {d['status']})\n"
                                     "AI-assisted extraction - review by an authorised engineer before use in design approval.\n")
        self.store.audit("system", "export", f"doc {doc_id}")
        return buf.getvalue()
