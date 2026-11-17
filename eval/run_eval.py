"""Evaluation harness computing Paper Table IV metrics + Hit@k & MRR (baseline vs hybrid)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.services.chunker import chunk_documents  # noqa: E402
from app.services.eligibility_engine import evaluate_eligibility  # noqa: E402
from app.services.gemini_client import GeminiClient  # noqa: E402
from app.services.language_service import FIXED_NOT_FOUND_EN  # noqa: E402
from app.services.pdf_extractor import extract_pdf_document  # noqa: E402
from app.services.rag_service import answer_question  # noqa: E402
from app.services.sample_library import get_scheme_by_id  # noqa: E402
from app.services.session_manager import SessionManager  # noqa: E402

SAMPLES_DIR = ROOT / "data" / "samples"
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
RESULTS_PATH = ROOT / "eval" / "results.json"
TABLE_MD_PATH = ROOT / "eval" / "table_iv.md"


def _load_corpus() -> tuple[list, list, dict[str, str]]:
    pdf_files = sorted(SAMPLES_DIR.glob("*.pdf"))
    extracted = []
    texts_by_file: dict[str, str] = {}
    for p in pdf_files:
        doc = extract_pdf_document(
            p.read_bytes(),
            p.name,
            enable_table_extraction=True,
            enable_ocr_fallback=False,
        )
        extracted.append(doc)
        texts_by_file[p.name] = "\n\n".join(pg.text for pg in doc.pages)
    chunks = chunk_documents(extracted, chunk_size=500, chunk_overlap=50)
    return extracted, chunks, texts_by_file


def _evaluate_mode(
    mode_name: str,
    questions: list[dict],
    extracted_docs: list,
    chunks: list,
    texts_by_file: dict[str, str],
    gemini: GeminiClient,
    run_llm: bool,
    enable_reranker: bool = False,
) -> dict:
    mgr = SessionManager()
    state, _ = mgr.update_documents(
        session_id=f"eval_{mode_name}",
        extracted_docs=extracted_docs,
        chunks=chunks,
        file_hashes=[d.filename for d in extracted_docs],
    )

    ret_targets = [q for q in questions if q.get("expected_sources")]
    hits = 0
    mrr_sum = 0.0
    latencies_ms: list[float] = []

    answerable_ok = 0
    answerable_total = 0
    not_found_ok = 0
    not_found_total = 0
    followup_ok = 0
    followup_total = 0
    citation_ok = 0
    citation_total = 0
    scheme_ok = 0
    scheme_total = 0

    for q in questions:
        q_type = q["type"]
        query_text = q["question"]

        # Measure retrieval Hit@k & MRR
        t0 = time.perf_counter()
        retrieved = state.vector_index.retrieve(
            query_text,
            top_k_max=20,
            mode=mode_name,
            enable_reranker=enable_reranker,
        )
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        exp_sources = q.get("expected_sources") or []
        if exp_sources:
            exp_pairs = {(s["filename"], int(s["page"])) for s in exp_sources}
            first_rank = None
            for rank, ch in enumerate(retrieved, start=1):
                if (ch.filename, int(ch.page)) in exp_pairs:
                    first_rank = rank
                    break
            if first_rank is not None:
                hits += 1
                mrr_sum += 1.0 / first_rank

        # Deterministic scheme availability check (always measurable)
        if q_type == "scheme":
            scheme_total += 1
            scheme_info = get_scheme_by_id(SAMPLES_DIR, q["scheme_id"])
            scheme_text = texts_by_file.get(scheme_info["filename"], "") if scheme_info else ""
            sub_citizen = {fn: texts_by_file[fn] for fn in q.get("citizen_docs", []) if fn in texts_by_file}
            elig = evaluate_eligibility(
                scheme_name=scheme_info["title"] if scheme_info else q["scheme_id"],
                scheme_text=scheme_text,
                citizen_texts_by_file=sub_citizen,
                gemini=None,
            )
            got_avail = sorted(item["document"] for item in elig["available_documents"])
            got_miss = sorted(elig["missing_documents"])
            exp_avail = sorted(q.get("expected_available", []))
            exp_miss = sorted(q.get("expected_missing", []))
            if got_avail == exp_avail and got_miss == exp_miss:
                scheme_ok += 1

        # End-to-end LLM evaluation (only when GEMINI_API_KEY is available & enabled)
        if run_llm:
            state.chat_history = list(q.get("prior_history", []))
            res = answer_question(
                state,
                query_text,
                gemini,
                retrieval_mode=mode_name,
                top_k_max=20,
                history_window=6,
                enable_reranker=enable_reranker,
                enable_multilingual=False,
            )
            ans_low = res.answer.lower()
            cited_pairs = {(s.filename, s.page) for s in res.sources}

            if exp_sources:
                citation_total += 1
                exp_pairs = {(s["filename"], int(s["page"])) for s in exp_sources}
                if exp_pairs & cited_pairs:
                    citation_ok += 1

            if q_type == "answerable":
                answerable_total += 1
                subs = q.get("expected_substrings", [])
                if subs and all(sub.lower() in ans_low for sub in subs) and not res.is_not_found:
                    answerable_ok += 1
            elif q_type == "not_found":
                not_found_total += 1
                if res.is_not_found or FIXED_NOT_FOUND_EN.lower() in ans_low:
                    not_found_ok += 1
            elif q_type == "followup":
                followup_total += 1
                subs = q.get("expected_substrings", [])
                if subs and all(sub.lower() in ans_low for sub in subs) and not res.is_not_found:
                    followup_ok += 1

    hit_rate = round((hits / len(ret_targets)) * 100.0, 1) if ret_targets else 0.0
    mrr = round(mrr_sum / len(ret_targets), 3) if ret_targets else 0.0
    avg_ret_ms = round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else 0.0
    scheme_acc = round((scheme_ok / scheme_total) * 100.0, 1) if scheme_total else 0.0

    grounding_rate = (
        round(((answerable_ok + followup_ok) / (answerable_total + followup_total)) * 100.0, 1)
        if run_llm and (answerable_total + followup_total)
        else None
    )
    citation_acc = (
        round((citation_ok / citation_total) * 100.0, 1)
        if run_llm and citation_total
        else hit_rate
    )
    nf_rate = (
        round((not_found_ok / not_found_total) * 100.0, 1)
        if run_llm and not_found_total
        else None
    )
    fu_rate = (
        round((followup_ok / followup_total) * 100.0, 1)
        if run_llm and followup_total
        else None
    )

    return {
        "hit_at_k": hit_rate,
        "mrr": mrr,
        "avg_retrieval_ms": avg_ret_ms,
        "available_missing_accuracy": scheme_acc,
        "grounding_rate": grounding_rate,
        "citation_accuracy": citation_acc,
        "not_found_rate": nf_rate,
        "followup_resolution_rate": fu_rate,
    }


def _fmt_pct(val: float | None) -> str:
    return f"{val}%" if val is not None else "N/A (requires GEMINI_API_KEY)"


def main() -> None:
    payload = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    questions = payload["questions"]
    extracted_docs, chunks, texts_by_file = _load_corpus()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    run_llm = bool(api_key) and "--retrieval-only" not in sys.argv
    gemini = GeminiClient(api_key=api_key, model=model)

    baseline = _evaluate_mode(
        "baseline", questions, extracted_docs, chunks, texts_by_file, gemini, run_llm=run_llm
    )
    hybrid = _evaluate_mode(
        "hybrid", questions, extracted_docs, chunks, texts_by_file, gemini, run_llm=run_llm
    )

    def _delta(b: float | None, h: float | None, suffix: str = "%") -> str:
        if b is None or h is None:
            return "—"
        diff = round(h - b, 3)
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff}{suffix}"

    comparison_rows = [
        {
            "metric": "Retrieval Hit@k",
            "baseline": f"{baseline['hit_at_k']}%",
            "hybrid": f"{hybrid['hit_at_k']}%",
            "baseline_num": baseline["hit_at_k"],
            "hybrid_num": hybrid["hit_at_k"],
            "delta": _delta(baseline["hit_at_k"], hybrid["hit_at_k"]),
        },
        {
            "metric": "Retrieval MRR",
            "baseline": f"{baseline['mrr']}",
            "hybrid": f"{hybrid['mrr']}",
            "baseline_num": round(baseline["mrr"] * 100.0, 1),
            "hybrid_num": round(hybrid["mrr"] * 100.0, 1),
            "delta": _delta(baseline["mrr"], hybrid["mrr"], suffix=""),
        },
        {
            "metric": "Available / Missing Accuracy",
            "baseline": f"{baseline['available_missing_accuracy']}%",
            "hybrid": f"{hybrid['available_missing_accuracy']}%",
            "baseline_num": baseline["available_missing_accuracy"],
            "hybrid_num": hybrid["available_missing_accuracy"],
            "delta": _delta(baseline["available_missing_accuracy"], hybrid["available_missing_accuracy"]),
        },
        {
            "metric": "Citation Source Coverage / Accuracy",
            "baseline": _fmt_pct(baseline["citation_accuracy"]),
            "hybrid": _fmt_pct(hybrid["citation_accuracy"]),
            "baseline_num": baseline["citation_accuracy"],
            "hybrid_num": hybrid["citation_accuracy"],
            "delta": _delta(baseline["citation_accuracy"], hybrid["citation_accuracy"]),
        },
        {
            "metric": "Grounding Rate (LLM)",
            "baseline": _fmt_pct(baseline["grounding_rate"]),
            "hybrid": _fmt_pct(hybrid["grounding_rate"]),
            "baseline_num": baseline["grounding_rate"],
            "hybrid_num": hybrid["grounding_rate"],
            "delta": _delta(baseline["grounding_rate"], hybrid["grounding_rate"]),
        },
        {
            "metric": "Correct 'Not Found' Rate (LLM)",
            "baseline": _fmt_pct(baseline["not_found_rate"]),
            "hybrid": _fmt_pct(hybrid["not_found_rate"]),
            "baseline_num": baseline["not_found_rate"],
            "hybrid_num": hybrid["not_found_rate"],
            "delta": _delta(baseline["not_found_rate"], hybrid["not_found_rate"]),
        },
        {
            "metric": "Follow-up Resolution Rate (LLM)",
            "baseline": _fmt_pct(baseline["followup_resolution_rate"]),
            "hybrid": _fmt_pct(hybrid["followup_resolution_rate"]),
            "baseline_num": baseline["followup_resolution_rate"],
            "hybrid_num": hybrid["followup_resolution_rate"],
            "delta": _delta(baseline["followup_resolution_rate"], hybrid["followup_resolution_rate"]),
        },
    ]

    note = (
        f"Full end-to-end retrieval + Gemini ({model}) generation evaluation across {len(questions)} questions."
        if run_llm
        else (
            f"Measured retrieval (Hit@k, MRR, source coverage) and deterministic Available/Missing "
            f"scheme accuracy across {len(questions)} benchmark questions. Live Gemini generation "
            f"metrics require GEMINI_API_KEY in .env and were not fabricated."
        )
    )

    results = {
        "dataset_size": len(questions),
        "evaluation_mode": "Full RAG (Retrieval + Gemini)" if run_llm else "Retrieval + Deterministic Rules",
        "note": note,
        "baseline": baseline,
        "hybrid": hybrid,
        "comparison_rows": comparison_rows,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    md_lines = [
        "### Evaluation Results (Table IV Format)",
        "",
        f"*{note}*",
        "",
        "| Metric | Paper Baseline (Vector k=min(20,N)) | Hybrid (BM25 + Vector RRF) | Delta |",
        "| --- | --- | --- | --- |",
    ]
    for r in comparison_rows:
        md_lines.append(f"| {r['metric']} | {r['baseline']} | {r['hybrid']} | {r['delta']} |")
    TABLE_MD_PATH.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print("\n".join(md_lines))


if __name__ == "__main__":
    main()
