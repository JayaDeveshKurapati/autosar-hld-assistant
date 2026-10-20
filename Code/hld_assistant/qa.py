"""Retrieval-augmented Q&A with mandatory citations.

Retrieval: TF-IDF over section chunks (identifier-aware tokenizer). This sits behind
`Retriever` so it can be swapped for FAISS/ChromaDB + BGE/E5 embeddings.
Generation: optional OpenAI-compatible LLM endpoint (HLD_LLM_URL / HLD_LLM_MODEL),
otherwise an extractive answer built from the best-matching sentences.
The LLM is instructed to answer only from the excerpts; if nothing relevant is
retrieved, the system declines rather than guessing.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

STOP = {"the", "a", "an", "of", "to", "is", "are", "what", "which", "who", "how", "does", "do", "in", "on",
        "for", "and", "or", "with", "by", "from", "that", "this", "it", "be", "as", "at", "me", "show", "list"}


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text):
        low = ident.lower()
        parts = [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", ident.replace("_", " "))]
        if len(parts) > 1:
            toks.append(low.replace("_", ""))  # whole identifier stays searchable
        toks.extend(parts)
    return [t for t in toks if t not in STOP and len(t) > 1]


@dataclass
class Hit:
    doc_id: int
    doc_name: str
    version: str
    status: str
    page: int
    section: str
    text: str
    score: float


class Retriever:
    def __init__(self, items: list[dict]):
        """items: dicts with doc_id, doc_name, version, status, page, section, text."""
        self.items = items
        self.vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, token_pattern=None, ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vec.fit_transform([f"{i['section']}\n{i['text']}" for i in items]) if items else None

    def search(self, query: str, k: int = 5) -> list[Hit]:
        if not self.items or not tokenize(query):
            return []
        scores = linear_kernel(self.vec.transform([query]), self.matrix).ravel()
        order = scores.argsort()[::-1][:k]
        return [Hit(**{**self.items[i]}, score=float(scores[i])) for i in order if scores[i] > 0]


MIN_SCORE = 0.08


def confidence(hits: list[Hit]) -> str:
    if not hits or hits[0].score < MIN_SCORE:
        return "none"
    return "high" if hits[0].score >= 0.35 else "medium" if hits[0].score >= 0.18 else "low"


def _extractive(question: str, hits: list[Hit]) -> str:
    q = set(tokenize(question))
    scored = []
    for n, h in enumerate(hits[:3], 1):
        for line in h.text.splitlines():
            line = line.strip(" -*•")
            if len(line) < 12:
                continue
            overlap = len(q & set(tokenize(line)))
            if overlap:
                scored.append((overlap, -n, line, n))
    scored.sort(reverse=True)
    lines = []
    for _, _, line, n in scored[:6]:
        if (line, n) not in lines:
            lines.append((line, n))
    if not lines:
        return "Relevant sections were found but no single statement answers the question directly - see the cited excerpts."
    return "\n".join(f"- {line} [{n}]" for line, n in lines)


def _llm_answer(question: str, hits: list[Hit]) -> str | None:
    url, model = os.getenv("HLD_LLM_URL"), os.getenv("HLD_LLM_MODEL")
    if not url or not model:
        return None
    excerpts = "\n\n".join(f"[{n}] ({h.doc_name} v{h.version}, p.{h.page}, {h.section})\n{h.text}" for n, h in enumerate(hits, 1))
    prompt = ("Answer the question using ONLY the numbered excerpts from an AUTOSAR High-Level Design document. "
              "Cite excerpts as [n] after each claim. If the excerpts do not contain the answer, say so.\n\n"
              f"Excerpts:\n{excerpts}\n\nQuestion: {question}")
    headers = {"Authorization": f"Bearer {os.environ['HLD_LLM_KEY']}"} if os.getenv("HLD_LLM_KEY") else {}
    try:
        r = requests.post(url.rstrip("/") + "/chat/completions", headers=headers, timeout=60,
                          json={"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception:  # fall back to extractive rather than fail the request
        return None


def answer(question: str, retriever: Retriever, k: int = 5) -> dict:
    hits = retriever.search(question, k)
    conf = confidence(hits)
    if conf == "none":
        return {"answer": "I could not find this in the selected documents. No answer is given to avoid guessing.",
                "confidence": "none", "mode": "declined", "citations": []}
    text = _llm_answer(question, hits)
    mode = "llm" if text else "extractive"
    if not text:
        text = _extractive(question, hits)
    warnings = sorted({f"{h.doc_name} v{h.version} is '{h.status}', not approved" for h in hits if h.status != "approved"})
    return {"answer": text, "confidence": conf, "mode": mode, "warnings": warnings,
            "citations": [{"n": n, "doc": h.doc_name, "version": h.version, "page": h.page,
                           "section": h.section, "score": round(h.score, 3), "excerpt": h.text[:600]}
                          for n, h in enumerate(hits, 1)]}
