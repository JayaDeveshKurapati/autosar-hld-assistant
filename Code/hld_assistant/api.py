"""FastAPI service layer.  Run: uvicorn hld_assistant.api:app --port 8000"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .service import Service

app = FastAPI(title="AUTOSAR HLD Analysis Assistant", version="0.1")
svc = Service()


class Ask(BaseModel):
    question: str
    doc_ids: list[int]


class Review(BaseModel):
    decision: str
    note: str = ""
    reviewer: str = "anonymous"


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/documents")
async def upload(file: UploadFile = File(...), project: str = Form("default"), version: str = Form("1.0"),
                 status: str = Form("draft")):
    return _guard(svc.ingest, project, file.filename, await file.read(), version, status)


@app.get("/documents")
def documents(project: str | None = None):
    return svc.store.list_documents(project)


@app.get("/documents/{doc_id}/extraction")
def extraction(doc_id: int):
    return asdict(_guard(svc.extraction, doc_id))


@app.get("/documents/{doc_id}/findings")
def findings(doc_id: int):
    return _guard(svc.findings, doc_id)


@app.post("/documents/{doc_id}/findings/{finding_id}/review")
def review(doc_id: int, finding_id: str, body: Review):
    _guard(svc.review_finding, doc_id, finding_id, body.decision, body.note, body.reviewer)
    return {"ok": True}


@app.get("/documents/{doc_id}/components/{name}")
def component(doc_id: int, name: str):
    r = _guard(svc.component_report, doc_id, name)
    if r is None:
        raise HTTPException(404, "component not found")
    return r


@app.get("/documents/{doc_id}/signals/{name}")
def signal(doc_id: int, name: str):
    return _guard(svc.signal_trace, doc_id, name)


@app.get("/compare")
def compare(old: int, new: int):
    return _guard(svc.compare, old, new)


@app.get("/compare/text")
def compare_text(old: int, new: int):
    return _guard(svc.text_diff, old, new)


@app.get("/documents/{doc_id}/requirements")
def reqs(doc_id: int):
    return _guard(svc.requirements, doc_id)


@app.get("/documents/{doc_id}/impact")
def impact(doc_id: int, kind: str, name: str):
    return _guard(svc.impact, doc_id, kind, name)


@app.get("/documents/{doc_id}/chains")
def chains(doc_id: int):
    return _guard(svc.chains, doc_id)


@app.get("/documents/{doc_id}/tests")
def tests(doc_id: int):
    return _guard(svc.test_plan, doc_id)


@app.get("/documents/{doc_id}/report", response_class=Response)
def report(doc_id: int):
    return Response(_guard(svc.report_html, doc_id), media_type="text/html")


class Status(BaseModel):
    status: str
    actor: str = "anonymous"


@app.post("/documents/{doc_id}/status")
def status(doc_id: int, body: Status):
    _guard(svc.set_status, doc_id, body.status, body.actor)
    return {"ok": True}


@app.get("/metrics")
def metrics(project: str = "default"):
    return svc.metrics(project)


@app.post("/ask")
def ask(body: Ask):
    return _guard(svc.ask, body.question, body.doc_ids)


@app.get("/documents/{doc_id}/export")
def export(doc_id: int):
    return Response(_guard(svc.export_zip, doc_id), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=hld_{doc_id}_export.zip"})
