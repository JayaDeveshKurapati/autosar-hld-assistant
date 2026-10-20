from pathlib import Path

import pytest

from hld_assistant.service import Service
from hld_assistant.store import Store

DATA = Path(__file__).parent.parent / "sample_data"


@pytest.fixture()
def svc():
    s = Service(Store(":memory:"))
    s.v1 = s.ingest("p", "v1.txt", (DATA / "brake_system_hld_v1.txt").read_bytes(), "1.0", "approved")["doc_id"]
    s.v2 = s.ingest("p", "v2.txt", (DATA / "brake_system_hld_v2.txt").read_bytes(), "2.0", "draft")["doc_id"]
    return s


def rules(svc, doc):
    return {f["rule"] for f in svc.findings(doc)}


def test_extraction_counts(svc):
    ex = svc.extraction(svc.v1)
    assert set(ex.components) == {"WheelSpeedProvider", "BrakeController", "ActuatorDriver"}
    assert len(ex.ports) == 5 and len(ex.connections) == 2
    assert ex.interfaces["IfWheelSpeed"]["elements"] == {"WheelSpeed": "uint16"}
    assert {r["name"]: r["period"] for r in ex.runnables}["Run_BrakeCtrl_10ms"] == "10 ms"


def test_v1_seeded_defects_found(svc):
    r = rules(svc, svc.v1)
    assert {"UNDEFINED_INTERFACE", "UNDEFINED_COMPONENT", "DATATYPE_MISMATCH",
            "SIGNAL_TYPE_CONFLICT", "UNCONNECTED_REQUIRE_PORT"} <= r
    msgs = " ".join(f["message"] for f in svc.findings(svc.v1))
    assert "IfActuatorCmd" in msgs and "DiagManager" in msgs


def test_v2_is_clean_of_errors(svc):
    assert not [f for f in svc.findings(svc.v2) if f["severity"] == "error"]


def test_compare(svc):
    rows = {(r["kind"], r["change"], r["item"]) for r in svc.compare(svc.v1, svc.v2)}
    assert ("component", "added", "VehicleSpeedEstimator") in rows
    assert ("interface", "added", "IfActuatorCmd") in rows
    assert ("connection", "added", "VehicleSpeedEstimator.VehicleSpeedOut -> BrakeController.VehicleSpeedIn") in rows
    assert ("runnable", "changed", "BrakeController.Run_BrakeCtrl_10ms") not in rows  # renamed, not changed
    assert ("runnable", "added", "BrakeController.Run_BrakeCtrl_5ms") in rows


def test_qa_cites_and_finds_right_section(svc):
    r = svc.ask("What is the period of the BrakeController runnable?", [svc.v1])
    assert r["confidence"] != "none"
    assert any(c["section"].startswith("3.2") for c in r["citations"][:3])
    assert all(c["page"] >= 1 for c in r["citations"])
    assert "10 ms" in r["answer"]


def test_qa_declines_when_not_in_document(svc):
    r = svc.ask("Explain the bluetooth pairing handshake", [svc.v1])
    assert r["confidence"] == "none" and r["citations"] == []


def test_qa_warns_on_unapproved_source(svc):
    r = svc.ask("latency requirement", [svc.v2])
    assert any("not approved" in w for w in r["warnings"])


def test_review_workflow_and_audit(svc):
    f = svc.findings(svc.v1)[0]
    svc.review_finding(svc.v1, f["id"], "confirmed", "real defect", "alice")
    assert svc.findings(svc.v1)[0]["review"]["decision"] == "confirmed"
    assert any(a["action"] == "review" for a in svc.store.audit_log())
    with pytest.raises(ValueError):
        svc.review_finding(svc.v1, f["id"], "bogus")


def test_export_zip(svc):
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(svc.export_zip(svc.v1)))
    assert {"extraction.json", "ports.csv", "findings.csv", "dependencies.dot"} <= set(z.namelist())


def test_pdf_ingest_roundtrip():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in (DATA / "brake_system_hld_v2.txt").read_text().splitlines():
        c.drawString(40, y, line)
        y -= 14
        if y < 40:
            c.showPage()
            y = 800
    c.save()
    s = Service(Store(":memory:"))
    res = s.ingest("p", "hld.pdf", buf.getvalue())
    assert res["components"] == 4 and res["connections"] == 3 and res["pages"] >= 1
    assert s.ask("who provides vehicle speed", [res["doc_id"]])["citations"]


def test_scanned_pdf_rejected():
    from reportlab.pdfgen import canvas
    import io

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    with pytest.raises(ValueError, match="OCR"):
        Service(Store(":memory:")).ingest("p", "scan.pdf", buf.getvalue())
