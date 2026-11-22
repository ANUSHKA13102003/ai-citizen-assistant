### System Accuracy Results

*Measured across 105 labelled questions over 32 fictional documents with distractors using live Gemini (gemini-3.1-flash-lite) with 4-second request spacing.*

| Measure | Vector-Only Search | Hybrid Search (Default) | Improvement |
| --- | --- | --- | --- |
| Search Hit Rate (Top-5) | 76.5% | 88.2% | +11.7% |
| Mean Reciprocal Rank (MRR) | 0.58 | 0.679 | +0.099 |
| Available / Missing Checklist Accuracy | 100.0% | 100.0% | 0.0% |
| Page Citation Accuracy | 97.7% | 100.0% | +2.3% |
| Grounded Answer Accuracy | 72.7% | 100.0% | +27.3% |
| Missing-Fact Refusal ('Not Found') Rate | 75.0% | 95.0% | +20.0% |
| Multi-Turn Follow-up Accuracy | 25.0% | 100.0% | +75.0% |
