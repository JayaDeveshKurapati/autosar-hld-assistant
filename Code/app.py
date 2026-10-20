"""Streamlit UI.  Run: streamlit run app.py"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from hld_assistant import reports, testgen
from hld_assistant.service import Service

st.set_page_config(page_title="AUTOSAR HLD Assistant", layout="wide")


@st.cache_resource
def get_service() -> Service:
    return Service()


svc = get_service()
ICON = {"error": "\U0001F534", "warning": "\U0001F7E0", "info": "\U0001F535"}
SAMPLES = (("brake_system_hld_v1.txt", "1.0"), ("brake_system_hld_v2.txt", "2.0"), ("brake_system.arxml", "1.0"))


def table(rows, **kw):
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", **kw)


st.title("AUTOSAR HLD Document Analysis Assistant")
st.caption("AI-assisted extraction and search. Every result cites its source; engineers review before any design decision.")

with st.sidebar:
    project = st.text_input("Project", "default")
    actor = st.text_input("Reviewer name", "engineer")
    if st.button("Load sample documents"):
        for f, ver in SAMPLES:
            svc.ingest(project, f, (Path(__file__).parent / "sample_data" / f).read_bytes(), ver, "draft", actor)
        st.rerun()
    st.divider()
    st.caption("LLM: " + ("configured (HLD_LLM_URL)" if os.getenv("HLD_LLM_URL") else "not configured - extractive answers"))

docs = svc.store.list_documents(project)
labels = {d["id"]: f"#{d['id']} {d['name']} v{d['version']} [{d['status']}]" for d in docs}


def pick(label, key, **kw):
    return st.selectbox(label, list(labels), format_func=labels.get, key=key, **kw)


tabs = st.tabs(["Documents", "Ask", "Architecture", "Findings", "Requirements", "Impact & timing",
                "Test plan", "Compare", "Metrics", "Export", "Audit log"])
(t_docs, t_ask, t_arch, t_find, t_req, t_imp, t_test, t_cmp, t_met, t_exp, t_audit) = tabs

with t_docs:
    up = st.file_uploader("Upload HLD (PDF, DOCX, TXT, MD) or ARXML", type=["pdf", "docx", "txt", "md", "arxml", "xml"])
    c1, c2 = st.columns(2)
    version = c1.text_input("Version label", "1.0")
    status = c2.selectbox("Source status", ["draft", "in_review", "approved"])
    if up and st.button("Ingest"):
        try:
            r = svc.ingest(project, up.name, up.getvalue(), version, status, actor)
            st.success(f"Ingested: {r['components']} components, {r['ports']} ports, {r['connections']} connections.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if docs:
        table([{k: v for k, v in d.items() if k != "ingested_at"} for d in docs])
        sel = pick("Manage document", "manage")
        a, b, c, _ = st.columns([1, 1, 1, 4])
        for col, label, new in ((a, "Send to review", "in_review"), (b, "Approve", "approved")):
            if col.button(label):
                try:
                    svc.set_status(sel, new, actor)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        if c.button("Delete"):
            svc.store.delete_document(sel)
            svc.store.audit(actor, "delete", f"doc {sel}")
            st.rerun()
    else:
        st.info("No documents yet - upload one or load the samples from the sidebar.")

with t_ask:
    if docs:
        chosen = st.multiselect("Search in", list(labels), default=list(labels)[-1:], format_func=labels.get)
        q = st.text_input("Question", placeholder="Which component provides WheelSpeed and who consumes it?")
        if q and chosen:
            r = svc.ask(q, chosen, actor)
            st.markdown(f"**Confidence:** {r['confidence']}  |  **Mode:** {r['mode']}")
            for w in r.get("warnings", []):
                st.warning(w)
            st.markdown(r["answer"])
            if r["facts"] and r["mode"] != "structured":
                with st.expander("Structured facts from the extraction", expanded=True):
                    for f in r["facts"]:
                        st.markdown(f"- {f['text']} _({f['doc']} v{f['version']}, p.{f['page']}, {f['section']})_")
            for c in r["citations"]:
                with st.expander(f"[{c['n']}] {c['doc']} v{c['version']} - p.{c['page']} - {c['section']} (score {c['score']})"):
                    st.code(c["excerpt"], language=None)

with t_arch:
    if docs:
        did = pick("Document", "arch")
        ex = svc.extraction(did)
        m = svc.summary(did)
        for col, (k, v) in zip(st.columns(len(m)), m.items()):
            col.metric(k, v)
        st.subheader("Dependency map")
        st.graphviz_chart(reports.dependency_dot(ex))
        st.subheader("Components")
        table([{"name": n, **{k: v for k, v in c.items() if k != "evidence"}} for n, c in ex.components.items()])
        st.subheader("Ports")
        table([{k: v for k, v in vars(p).items() if k != "evidence"} for p in ex.ports])
        st.subheader("Interfaces")
        table([{"name": n, "kind": i["kind"], "elements": ", ".join(f"{k}: {v}" for k, v in i["elements"].items())}
               for n, i in ex.interfaces.items()])
        comp = st.selectbox("Component report", list(ex.components) or [""])
        if comp:
            st.json(svc.component_report(did, comp), expanded=False)
        sigs = sorted({p.signal for p in ex.ports if p.signal})
        if sigs:
            st.json(svc.signal_trace(did, st.selectbox("Signal trace", sigs)), expanded=False)

with t_find:
    if docs:
        did = pick("Document", "find")
        fs = svc.findings(did)
        st.caption(f"{len(fs)} candidate findings - prompts for review, not verdicts. Errors need a decision before approval.")
        sev = st.multiselect("Severity", ["error", "warning", "info"], default=["error", "warning"])
        only_open = st.checkbox("Only unreviewed")
        for f in (f for f in fs if f["severity"] in sev and not (only_open and f["review"])):
            state = (f["review"] or {}).get("decision", "open")
            with st.expander(f"{ICON[f['severity']]} {f['rule']} - {f['message']}  ({state})"):
                st.write(f"Source: page {f['page']}, section {f['section']}")
                if f["evidence"]:
                    st.code(f["evidence"], language=None)
                note = st.text_input("Note", (f["review"] or {}).get("note") or "", key=f"n{f['id']}")
                cols = st.columns([1, 1, 1, 4])
                for col, dec in zip(cols, ("confirmed", "dismissed", "open")):
                    if col.button(dec.capitalize(), key=f"{dec}{f['id']}"):
                        svc.review_finding(did, f["id"], dec, note, actor)
                        st.rerun()

with t_req:
    if docs:
        did = pick("Document", "req")
        reqs = svc.requirements(did)
        st.caption(f"{len(reqs)} requirement statements ('shall'/'must'), linked to the architecture entities they mention.")
        table([{"id": r["id"], "kind": r["kind"], "text": r["text"], "limit_ms": r["limit_ms"],
                "linked": ", ".join(e["name"] for e in r["entities"]) or "-", "page": r["page"]} for r in reqs])

with t_imp:
    if docs:
        did = pick("Document", "imp")
        ex = svc.extraction(did)
        st.subheader("Change impact")
        c1, c2 = st.columns(2)
        kind = c1.selectbox("Entity kind", ["component", "signal", "interface"])
        pool = {"component": list(ex.components), "signal": sorted({p.signal for p in ex.ports if p.signal}),
                "interface": list(ex.interfaces)}[kind]
        name = c2.selectbox("Entity", pool or [""])
        if name:
            r = svc.impact(did, kind, name)
            st.write("Directly affected:", ", ".join(r["directly_affected"]) or "-")
            st.write("Downstream (consumers):")
            table(r["downstream"])
            st.write("Upstream (providers):")
            table(r["upstream"])
        st.subheader("End-to-end chains")
        st.caption("Latency = sum of each component's slowest runnable period (rough worst-case sampling delay; "
                   "ignores execution and bus time).")
        table([{"chain": " -> ".join(c["path"]), "est_latency_ms": c["latency_ms"], "unknown_periods": ", ".join(c["unknown"])}
               for c in svc.chains(did)])

with t_test:
    if docs:
        did = pick("Document", "test")
        plan = svc.test_plan(did)
        kinds = st.multiselect("Type", sorted({t["type"] for t in plan}), default=sorted({t["type"] for t in plan}))
        shown = [t for t in plan if t["type"] in kinds]
        st.caption(f"{len(shown)} of {len(plan)} generated test case skeletons, each traced to an entity and source section.")
        table(shown)
        st.download_button("Download tests.csv", pd.DataFrame(plan, columns=testgen.COLUMNS).to_csv(index=False),
                           file_name="tests.csv")

with t_cmp:
    if len(docs) < 2:
        st.info("Ingest at least two revisions to compare.")
    else:
        ids = list(labels)
        old = st.selectbox("Old revision", ids, format_func=labels.get, index=0)
        new = st.selectbox("New revision", ids, format_func=labels.get, index=len(ids) - 1)
        st.subheader("Structural changes")
        rows = svc.compare(old, new)
        table(rows) if rows else st.success("No structural differences.")
        st.subheader("Text changes by section")
        for r in svc.text_diff(old, new):
            with st.expander(f"{r['status'].upper()}: {r['section']}" + (f"  - {len(r['value_changes'])} value change(s)" if r["value_changes"] else "")):
                for v in r["value_changes"]:
                    st.markdown(f"**{v['old']}** → **{v['new']}**")
                if r["diff"]:
                    st.code(r["diff"], language="diff")

with t_met:
    m = svc.metrics(project)
    c = st.columns(4)
    c[0].metric("Documents", m["documents"])
    c[1].metric("Finding precision", f"{m['finding_precision_pct']}%" if m["finding_precision_pct"] is not None else "n/a",
                help="confirmed / (confirmed + dismissed) among reviewed findings")
    c[2].metric("Requirement traceability", f"{m['requirement_trace_pct']}%" if m["requirement_trace_pct"] is not None else "n/a")
    c[3].metric("Answer groundedness", f"{m['groundedness_pct']}%" if m["groundedness_pct"] is not None else "n/a",
                help="answered questions that carry at least one citation")
    st.write("Findings by severity:", m["findings_by_severity"], " Reviews:", m["reviews"])
    st.write(f"Questions asked: {m['questions']}  |  answered: {m['answer_rate_pct']}%")

with t_exp:
    if docs:
        did = pick("Document", "exp")
        st.download_button("Download export (ZIP: JSON, CSVs, tests, DOT, HTML report)", svc.export_zip(did),
                           file_name=f"hld_{did}_export.zip")
        st.download_button("Download review report (HTML, print to PDF)", svc.report_html(did),
                           file_name=f"hld_{did}_review.html", mime="text/html")

with t_audit:
    table(svc.store.audit_log())
