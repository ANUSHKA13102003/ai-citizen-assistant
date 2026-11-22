"""Evaluation harness over 32 fictional documents and 105 questions with live Gemini & 4s spacing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.config import clean_model_name  # noqa: E402
from app.services.chunker import chunk_documents  # noqa: E402
from app.services.eligibility_engine import DOCUMENT_ALIASES, evaluate_eligibility  # noqa: E402
from app.services.gemini_client import GeminiClient  # noqa: E402
from app.services.language_service import FIXED_NOT_FOUND_EN  # noqa: E402
from app.services.pdf_extractor import extract_pdf_document  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    _format_context_blocks,
    deduplicate_sources,
    rewrite_followup_query,
)
from app.services.sample_library import get_scheme_by_id  # noqa: E402
from app.services.session_manager import SessionManager  # noqa: E402

EVAL_DIR = ROOT / "data" / "eval"
DOCS_DIR = EVAL_DIR / "docs"
QUESTIONS_PATH = EVAL_DIR / "questions.json"
RESULTS_PATH = EVAL_DIR / "results.json"
CACHE_PATH = EVAL_DIR / "llm_cache.json"
LEGACY_RESULTS_PATH = ROOT / "eval" / "results.json"
TABLE_MD_PATH = ROOT / "eval" / "table_iv.md"
SCHEMES_PATH = ROOT / "data" / "schemes" / "schemes.json"
SAMPLES_DIR = ROOT / "data" / "samples"


def _load_corpus() -> tuple[list, list, dict[str, str]]:
    if not DOCS_DIR.exists() or not list(DOCS_DIR.glob("*.pdf")):
        from scripts.build_eval_dataset import main as build_ds

        build_ds()
    pdf_files = sorted(DOCS_DIR.glob("*.pdf"))
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


def _expected_scheme_checklist(
    scheme: dict, sub_citizen: dict[str, str]
) -> tuple[list[str], list[str]]:
    req_docs = list(scheme.get("required_documents") or [])
    avail: list[str] = []
    miss: list[str] = []
    combined = "\n".join(f"{fn}\n{txt}" for fn, txt in sub_citizen.items()).lower()
    for doc_type in req_docs:
        kws = DOCUMENT_ALIASES.get(doc_type, [])
        if any(kw in combined for kw in kws):
            avail.append(doc_type)
        else:
            miss.append(doc_type)
    return sorted(avail), sorted(miss)


def _load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_batched_llm(
    pending_items: list[dict],
    gemini: GeminiClient,
    llm_cache: dict[str, str],
    spacing_seconds: float = 4.0,
    batch_size: int = 16,
) -> None:
    """Evaluate uncached RAG items in structured batches with 4-second spacing and retry/backoff."""
    if not pending_items:
        return

    system_prompt = (
        "You are AI Citizen Assistant evaluating grounded document Q&A items.\n"
        "For each item in the input array, answer ONLY using its provided Context Chunks and Prior History.\n"
        f'If the answer is not present in the item\'s Context Chunks, set answer to exact string: "{FIXED_NOT_FOUND_EN}".\n'
        "Return a valid JSON object mapping each item's `key` to its grounded answer string."
    )

    for start in range(0, len(pending_items), batch_size):
        batch = pending_items[start : start + batch_size]
        prompt_items = [
            {
                "key": item["cache_key"],
                "question": item["question"],
                "prior_history": item["history"],
                "context_chunks": item["context"],
            }
            for item in batch
        ]
        raw = gemini.generate(
            system_prompt=system_prompt,
            user_prompt=json.dumps(prompt_items, ensure_ascii=False),
            temperature=0.0,
            response_mime_type="application/json",
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            for item in batch:
                k = item["cache_key"]
                if k in parsed and parsed[k]:
                    llm_cache[k] = str(parsed[k]).strip()
        _save_cache(llm_cache)
        print(
            f"Completed live Gemini batch {start // batch_size + 1} ({len(batch)} questions) using {gemini.model}"
        )
        if start + batch_size < len(pending_items):
            time.sleep(spacing_seconds)


def _evaluate_mode(
    mode_name: str,
    questions: list[dict],
    extracted_docs: list,
    chunks: list,
    texts_by_file: dict[str, str],
    gemini: GeminiClient,
    run_llm: bool,
    llm_cache: dict[str, str],
    spacing_seconds: float = 4.0,
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

    top_k_eval = 5
    prepared_llm_items: list[dict] = []

    for q in questions:
        q_type = q["type"]
        query_text = q["question"]
        history = list(q.get("prior_history", []))
        search_query = (
            rewrite_followup_query(query_text, history) if mode_name == "hybrid" else query_text
        )

        t0 = time.perf_counter()
        retrieved = state.vector_index.retrieve(
            search_query,
            top_k_max=top_k_eval,
            mode=mode_name,
            enable_reranker=False,
            adaptive_k=False,
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

        if q_type == "scheme":
            scheme_total += 1
            scheme_info = get_scheme_by_id(
                SAMPLES_DIR, q["scheme_id"], schemes_path=SCHEMES_PATH
            )
            sub_citizen = {
                fn: texts_by_file[fn] for fn in q.get("citizen_docs", []) if fn in texts_by_file
            }
            if scheme_info:
                elig = evaluate_eligibility(
                    scheme_name=scheme_info.get("name", q["scheme_id"]),
                    scheme_text="",
                    citizen_texts_by_file=sub_citizen,
                    gemini=None,
                    structured_scheme=scheme_info,
                )
                got_avail = sorted(item["document"] for item in elig["available_documents"])
                got_miss = sorted(elig["missing_documents"])
                exp_avail, exp_miss = _expected_scheme_checklist(scheme_info, sub_citizen)
                if got_avail == exp_avail and got_miss == exp_miss:
                    scheme_ok += 1
            continue

        if run_llm:
            context_block = _format_context_blocks(retrieved)
            cache_key = hashlib.sha256(
                f"{q['id']}||{query_text}||{json.dumps(history)}||{context_block}".encode()
            ).hexdigest()[:24]
            prepared_llm_items.append(
                {
                    "q": q,
                    "retrieved": retrieved,
                    "cache_key": cache_key,
                    "question": query_text,
                    "history": history,
                    "context": context_block,
                }
            )

    if run_llm:
        uncached = [item for item in prepared_llm_items if item["cache_key"] not in llm_cache]
        _run_batched_llm(
            uncached, gemini, llm_cache, spacing_seconds=spacing_seconds, batch_size=16
        )

        for item in prepared_llm_items:
            q = item["q"]
            q_type = q["type"]
            retrieved = item["retrieved"]
            answer_text = llm_cache.get(item["cache_key"], "")
            ans_low = answer_text.lower()
            is_nf = FIXED_NOT_FOUND_EN.lower() in ans_low
            sources = [] if is_nf else deduplicate_sources(retrieved)
            cited_pairs = {(s.filename, s.page) for s in sources}

            exp_sources = q.get("expected_sources") or []
            if exp_sources:
                citation_total += 1
                exp_pairs = {(s["filename"], int(s["page"])) for s in exp_sources}
                if exp_pairs & cited_pairs:
                    citation_ok += 1

            if q_type == "answerable":
                answerable_total += 1
                subs = q.get("expected_substrings", [])
                if subs and all(sub.lower() in ans_low for sub in subs) and not is_nf:
                    answerable_ok += 1
            elif q_type == "not_found":
                not_found_total += 1
                if is_nf:
                    not_found_ok += 1
            elif q_type == "followup":
                followup_total += 1
                subs = q.get("expected_substrings", [])
                if subs and all(sub.lower() in ans_low for sub in subs) and not is_nf:
                    followup_ok += 1

    mgr.clear_session(f"eval_{mode_name}")

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
    if not QUESTIONS_PATH.exists():
        from scripts.build_eval_dataset import main as build_ds

        build_ds()

    payload = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    questions = payload["questions"]
    extracted_docs, chunks, texts_by_file = _load_corpus()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = clean_model_name(os.getenv("GEMINI_MODEL"))
    run_llm = bool(api_key) and "--retrieval-only" not in sys.argv
    gemini = GeminiClient(api_key=api_key, model=model)
    llm_cache = _load_cache()

    hybrid = _evaluate_mode(
        "hybrid",
        questions,
        extracted_docs,
        chunks,
        texts_by_file,
        gemini,
        run_llm=run_llm,
        llm_cache=llm_cache,
        spacing_seconds=4.0,
    )
    baseline = _evaluate_mode(
        "baseline",
        questions,
        extracted_docs,
        chunks,
        texts_by_file,
        gemini,
        run_llm=run_llm,
        llm_cache=llm_cache,
        spacing_seconds=4.0,
    )

    def _delta(b: float | None, h: float | None, suffix: str = "%") -> str:
        if b is None or h is None:
            return "—"
        diff = round(h - b, 3)
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff}{suffix}"

    comparison_rows = [
        {
            "metric": "Search Hit Rate (Top-5)",
            "baseline": f"{baseline['hit_at_k']}%",
            "hybrid": f"{hybrid['hit_at_k']}%",
            "baseline_num": baseline["hit_at_k"],
            "hybrid_num": hybrid["hit_at_k"],
            "delta": _delta(baseline["hit_at_k"], hybrid["hit_at_k"]),
        },
        {
            "metric": "Mean Reciprocal Rank (MRR)",
            "baseline": f"{baseline['mrr']}",
            "hybrid": f"{hybrid['mrr']}",
            "baseline_num": round(baseline["mrr"] * 100.0, 1),
            "hybrid_num": round(hybrid["mrr"] * 100.0, 1),
            "delta": _delta(baseline["mrr"], hybrid["mrr"], suffix=""),
        },
        {
            "metric": "Available / Missing Checklist Accuracy",
            "baseline": f"{baseline['available_missing_accuracy']}%",
            "hybrid": f"{hybrid['available_missing_accuracy']}%",
            "baseline_num": baseline["available_missing_accuracy"],
            "hybrid_num": hybrid["available_missing_accuracy"],
            "delta": _delta(
                baseline["available_missing_accuracy"], hybrid["available_missing_accuracy"]
            ),
        },
        {
            "metric": "Page Citation Accuracy",
            "baseline": _fmt_pct(baseline["citation_accuracy"]),
            "hybrid": _fmt_pct(hybrid["citation_accuracy"]),
            "baseline_num": baseline["citation_accuracy"],
            "hybrid_num": hybrid["citation_accuracy"],
            "delta": _delta(baseline["citation_accuracy"], hybrid["citation_accuracy"]),
        },
        {
            "metric": "Grounded Answer Accuracy",
            "baseline": _fmt_pct(baseline["grounding_rate"]),
            "hybrid": _fmt_pct(hybrid["grounding_rate"]),
            "baseline_num": baseline["grounding_rate"],
            "hybrid_num": hybrid["grounding_rate"],
            "delta": _delta(baseline["grounding_rate"], hybrid["grounding_rate"]),
        },
        {
            "metric": "Missing-Fact Refusal ('Not Found') Rate",
            "baseline": _fmt_pct(baseline["not_found_rate"]),
            "hybrid": _fmt_pct(hybrid["not_found_rate"]),
            "baseline_num": baseline["not_found_rate"],
            "hybrid_num": hybrid["not_found_rate"],
            "delta": _delta(baseline["not_found_rate"], hybrid["not_found_rate"]),
        },
        {
            "metric": "Multi-Turn Follow-up Accuracy",
            "baseline": _fmt_pct(baseline["followup_resolution_rate"]),
            "hybrid": _fmt_pct(hybrid["followup_resolution_rate"]),
            "baseline_num": baseline["followup_resolution_rate"],
            "hybrid_num": hybrid["followup_resolution_rate"],
            "delta": _delta(
                baseline["followup_resolution_rate"], hybrid["followup_resolution_rate"]
            ),
        },
    ]

    active_model = gemini.model if run_llm else "offline"
    note = (
        f"Measured across {len(questions)} labelled questions over {len(extracted_docs)} fictional "
        f"documents with distractors using live Gemini ({active_model}) with 4-second request spacing."
        if run_llm
        else (
            f"Measured search (Top-5 Hit Rate, MRR) and checklist accuracy across {len(questions)} "
            f"questions over {len(extracted_docs)} fictional documents."
        )
    )

    results = {
        "dataset_size": len(questions),
        "document_count": len(extracted_docs),
        "evaluation_mode": f"Live Gemini ({active_model})" if run_llm else "Search + Rules",
        "note": note,
        "baseline": baseline,
        "hybrid": hybrid,
        "comparison_rows": comparison_rows,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if LEGACY_RESULTS_PATH.parent.exists():
        LEGACY_RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    md_lines = [
        "### System Accuracy Results",
        "",
        f"*{note}*",
        "",
        "| Measure | Vector-Only Search | Hybrid Search (Default) | Improvement |",
        "| --- | --- | --- | --- |",
    ]
    for r in comparison_rows:
        md_lines.append(f"| {r['metric']} | {r['baseline']} | {r['hybrid']} | {r['delta']} |")
    if TABLE_MD_PATH.parent.exists():
        TABLE_MD_PATH.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print("\n".join(md_lines))


if __name__ == "__main__":
    main()
