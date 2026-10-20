# Configuration

| Item | Value | Where |
|---|---|---|
| Retriever | scikit-learn TfidfVectorizer, ngram (1,2), sublinear_tf, identifier-aware tokenizer | Code/hld_assistant/qa.py |
| Top-k chunks | 5 | qa.py `answer(k=5)` |
| Refusal threshold | top score < 0.08 -> decline | qa.py `MIN_SCORE` |
| Confidence buckets | high >= 0.35, medium >= 0.18, low >= 0.08 | qa.py `confidence()` |
| LLM (optional) | any OpenAI-compatible endpoint, temperature 0 | env vars below |
| Pre-trained model used in evaluation | none (extractive mode) | - |
| Database | SQLite `data/hld.sqlite` | store.py |

Environment variables (all optional):
```
HLD_LLM_URL=http://localhost:11434/v1
HLD_LLM_MODEL=llama3.1
HLD_LLM_KEY=<only if the endpoint needs one>
```
Python packages: see Code/requirements.txt
