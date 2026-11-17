### Evaluation Results (Table IV Format)

*Measured retrieval (Hit@k, MRR, source coverage) and deterministic Available/Missing scheme accuracy across 62 benchmark questions. Live Gemini generation metrics require GEMINI_API_KEY in .env and were not fabricated.*

| Metric | Paper Baseline (Vector k=min(20,N)) | Hybrid (BM25 + Vector RRF) | Delta |
| --- | --- | --- | --- |
| Retrieval Hit@k | 100.0% | 100.0% | 0.0% |
| Retrieval MRR | 0.83 | 0.881 | +0.051 |
| Available / Missing Accuracy | 100.0% | 100.0% | 0.0% |
| Citation Source Coverage / Accuracy | 100.0% | 100.0% | 0.0% |
| Grounding Rate (LLM) | N/A (requires GEMINI_API_KEY) | N/A (requires GEMINI_API_KEY) | — |
| Correct 'Not Found' Rate (LLM) | N/A (requires GEMINI_API_KEY) | N/A (requires GEMINI_API_KEY) | — |
| Follow-up Resolution Rate (LLM) | N/A (requires GEMINI_API_KEY) | N/A (requires GEMINI_API_KEY) | — |
