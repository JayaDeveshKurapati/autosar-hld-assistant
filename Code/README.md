# AUTOSAR HLD Document Analysis Assistant (Case Study 1 pilot)

Ingest AUTOSAR High-Level Design documents (PDF, DOCX, TXT/MD) or ARXML, extract the architecture,
search it with cited answers, flag inconsistencies, trace requirements, estimate timing, compare
revisions, generate test skeletons and export a review report.

```
pip install -r requirements.txt
streamlit run app.py                         # UI (sidebar: "Load sample documents")
uvicorn hld_assistant.api:app --port 8000    # REST API
python -m hld_assistant analyze hld.pdf      # CLI / CI gate, exits 1 on errors (--fail-on warning|never, --json)
python -m hld_assistant compare old.pdf new.pdf
pytest                                       # 27 tests
```

## Features
| Area | What it does |
|---|---|
| Ingestion | PDF, DOCX (headings auto-numbered, tables flattened), TXT/MD, **ARXML** (interfaces, SWCs, ports, runnables + timing events, composition connectors) |
| Extraction | Components, interfaces, ports, signals, runnables, dependencies, connections - each with page, section and evidence |
| Findings | 15 rules: undefined interface/component/port, type mismatch, signal type conflict, wrong direction, unconnected ports, dependency without connection, duplicate port, **dependency cycles**, **rate mismatch**, naming inconsistency, untraced requirement, **timing budget exceeded** |
| Review workflow | Confirm/dismiss with notes; **approval is blocked until every error has a decision**; draft -> in_review -> approved |
| Requirements | "shall/must" statements, typed (timing/safety/functional), numeric limits parsed, linked to the entities they mention |
| Impact & timing | Change impact (up/downstream) for a component, signal or interface; source-to-sink chains with a rough worst-case sampling-latency estimate |
| Q&A | Cited TF-IDF retrieval + **structured facts** from the extraction (who provides/consumes a signal, component summary); declines instead of guessing; warns on unapproved sources; optional LLM |
| Compare | Structural diff **and section text diff with value-change detection** (e.g. `20 ms -> 15 ms`) |
| Test plan | Traced test-case skeletons: signal propagation, silent provider, boundary values, activation period, requirement verification, fault reaction |
| Metrics | Finding precision from reviews, requirement traceability, answer rate, groundedness |
| Export | ZIP (JSON, CSVs incl. requirements/tests/findings, DOT graph) and a printable HTML review report with sign-off block |
| Governance | Audit log of every ingest, question, review, status change and export |

## Layout
`ingest.py` `arxml.py` `extract.py` -> `checks.py` `requirements.py` `impact.py` `compare.py` `testgen.py`
`qa.py` `reports.py` `reportgen.py` -> `service.py` (single facade) -> `api.py` / `cli.py` / `app.py`.
State is SQLite (`data/hld.sqlite`).

## LLM (optional)
Without an LLM, answers are extractive. For generated answers set an OpenAI-compatible endpoint
(Ollama, vLLM, llama.cpp server...): `HLD_LLM_URL=http://localhost:11434/v1 HLD_LLM_MODEL=llama3.1`
(optional `HLD_LLM_KEY`). The prompt restricts the model to the retrieved excerpts.

## Known limits
- The text extractor expects the conventions in `sample_data/` (headings like `3.2 Name (ApplicationSwComponentType)`,
  `P-Port/R-Port name: interface X, signal Y, type Z`, `A.p -> B.q`). Other layouts need pattern tuning or an
  LLM extractor feeding the same schema. ARXML import is the robust path for real projects.
- Latency estimates are coarse (sampling delay only); treat them as a screening aid, not timing analysis.
- Retrieval is TF-IDF; swap `Retriever` for FAISS/ChromaDB + BGE/E5 embeddings.
- No OCR, no table/diagram extraction from PDFs, no authentication or role-based access (the reviewer name is
  self-declared; projects are separated by name only).
