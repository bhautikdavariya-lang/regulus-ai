"""Plain-text report rendering for a saved evaluation run."""

from __future__ import annotations

from regulus.evaluation.dataset import CATEGORIES
from regulus.evaluation.results import MANUAL_SCORES, EvaluationRun, QuestionResult, aggregate


def _fmt(value, unit: str = "", digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}{unit}"
    return f"{value}{unit}"


def render_summary(run: EvaluationRun) -> str:
    meta = run.run
    summary = run.summary or aggregate(run.results)
    gen = meta.get("generation", {})
    ds = meta.get("dataset", {})
    lines = [
        "Baseline Evaluation Report",
        "=" * 26,
        f"Run id:      {meta.get('evaluation_run_id')}",
        f"Pipeline:    {meta.get('pipeline')}",
        f"Timestamp:   {meta.get('timestamp_utc')}",
        f"Model:       {meta.get('model_id')}  (revision {meta.get('model_revision') or 'unknown'})",
        f"Device:      {meta.get('device')}  dtype {meta.get('dtype')}",
        f"Dataset:     {ds.get('name')}  ({ds.get('num_examples')} examples, sha256 {str(ds.get('sha256'))[:12]}...)",
        f"Decoding:    {meta.get('decoding_mode')}  max_new_tokens={gen.get('max_new_tokens')}"
        + (
            f"  temperature={gen.get('temperature')} top_p={gen.get('top_p')} top_k={gen.get('top_k')}"
            if meta.get("decoding_mode") == "sampling"
            else ""
        )
        + f"  thinking={gen.get('enable_thinking')}",
        f"Questions:   {summary.get('total')}",
        "",
        "Completion",
        "----------",
        f"Completed: {summary.get('completed')}",
        f"Failed:    {summary.get('failed')}" + (f"  {summary.get('failed_ids')}" if summary.get("failed") else ""),
        f"Total:     {summary.get('total')}",
        "",
        "Generation performance",
        "----------------------",
        f"Average latency:       {_fmt(summary.get('avg_generation_seconds'), ' s')}",
        f"Average input tokens:  {_fmt(summary.get('avg_input_tokens'), '', 1)}",
        f"Average output tokens: {_fmt(summary.get('avg_output_tokens'), '', 1)}",
        f"Average speed:         {_fmt(summary.get('avg_tokens_per_second'), ' tok/s')}",
        f"Total run time:        {_fmt(meta.get('duration_seconds'), ' s', 1)}",
        "",
        "Questions by category",
        "---------------------",
    ]
    for key, label in CATEGORIES.items():
        row = summary.get("by_category", {}).get(key)
        if row:
            failed = f" ({row['failed']} failed)" if row["failed"] else ""
            lines.append(f"{label + ':':<24}{row['total']}{failed}")

    manual = summary.get("manual_evaluation", {})
    lines += ["", "Manual quality scoring", "----------------------"]
    if manual.get("scored"):
        lines.append(f"Scored: {manual['scored']} / {summary.get('total')}   mean score: {_fmt(manual.get('mean_score'))} (0-2)")
        for key, value in (manual.get("by_category") or {}).items():
            lines.append(f"  {CATEGORIES.get(key, key) + ':':<24}{_fmt(value)}")
    else:
        lines.append("No questions scored yet. Fill in quality_score (0/1/2) and manual_evaluation in the results file.")
    return "\n".join(lines)


def render_answers(run: EvaluationRun, category: str | None = None, ids: set[str] | None = None) -> str:
    rows: list[QuestionResult] = run.results
    if category:
        rows = [r for r in rows if r.category == category]
    if ids:
        rows = [r for r in rows if r.question_id in ids]
    if not rows:
        return "(no matching questions)"
    blocks = []
    for r in rows:
        head = f"[{r.question_id}] {CATEGORIES.get(r.category, r.category)} | expected: {r.expected_behavior} | {r.status}"
        parts = [head, "-" * len(head), f"Q: {r.question}", ""]
        if r.status == "completed":
            parts += [f"A: {r.model_answer}", ""]
            parts.append(
                f"({r.input_tokens} in / {r.output_tokens} out tokens, {_fmt(r.generation_seconds, ' s')}, "
                f"{_fmt(r.tokens_per_second, ' tok/s')})"
            )
        else:
            parts.append(f"ERROR: {r.error}")
        if r.diagnostics:
            retrieved = r.diagnostics.get("retrieved") or []
            used = {s.get("index"): s for s in (r.diagnostics.get("context") or {}).get("sources", [])}
            parts.append("")
            parts.append(f"Retrieved ({len(retrieved)}), in context ({len(used)}), no_context={r.diagnostics.get('no_context')}:")
            for item in retrieved[:6]:
                mark = "*" if any(u.get("key") == item.get("key") for u in used.values()) else " "
                parts.append(f"  {mark} {item['rank']}. [{item['corpus']}] {item['citation'][:90]}  score={item['score']} method={item['method']}")
        parts += ["", f"Reference: {r.reference_answer}", f"Notes: {r.evaluation_notes}"]
        score = r.quality_score
        parts.append(f"Score: {score} ({MANUAL_SCORES.get(score, '?')})" if score is not None else "Score: not evaluated")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)
