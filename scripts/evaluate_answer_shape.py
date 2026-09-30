"""Stage 12 answer-shape evaluation: the live pipeline on a small, hand-checked set.

    python scripts/evaluate_answer_shape.py --label after
    python scripts/evaluate_answer_shape.py --label shape_off --answer-shape off
    python scripts/evaluate_answer_shape.py --ids AS-01 AS-03

Each question goes through the Stage 5 full-pipeline path
(`regulus.stage5.generation_eval.run_full`: the configured pipeline under the
evaluation protocol, raw answer kept, repair derived from it), so the raw
answer, the repaired answer, both validation reports, the claim-level
faithfulness heuristic, citations, tokens and timings are exactly what
Stage 5 records. This script adds the answer-shape dimensions on top.

Every dimension is reported on its own. Nothing is combined into a score:

    shape        detected mode / scope / exhaustive vs. the expected ones
    coverage     required points present in the raw answer (hand-fixed terms)
    qualifiers   conditional wording present ("if applicable", ...)
    scope        out-of-scope terms present (focused / comparison questions)
    citations    validity (Stage 5 citation_ok) and distinct markers
    grounding    validation status, claim support counts (heuristic)
    repetition   near-duplicate sentence pairs
    dump         provision-led blocks (one block per evidence row)
    tokens       generated, allowance, finished, truncated
    latency      generation and total milliseconds

The metrics here are computed from the answer text alone, independently of
the Stage 12 validator, so a run of the pre-Stage-12 code is measured with
the same yardstick. Output: artifacts/answer_shape/<label>_<utc>/.
The database is read-only and nothing outside the output directory is written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from regulus.config import PROJECT_ROOT, load_settings
from regulus.evaluation.grounding_eval import split_sentences
from regulus.rag import RagPipeline, load_qwen_generator  # noqa: F401  (imported up front on purpose)
from regulus.retrieval import Database, LexicalRetriever
from regulus.stage5.dataset import Stage5Example
from regulus.stage5.generation_eval import run_full
from regulus.system_identity import configured_generation_config, evaluation_rag_config

DEFAULT_DATASET = PROJECT_ROOT / "data" / "evaluation" / "datasets" / "answer_shape_v1.jsonl"
OUT_ROOT = PROJECT_ROOT / "artifacts" / "answer_shape"

_MARK = re.compile(r"\[(\d{1,2})\]")
_WORD = re.compile(r"[a-z][a-z'-]{2,}")
_STOP = {"the", "and", "for", "with", "that", "this", "must", "shall", "are", "any", "all", "from", "under", "part", "cfr",
         "section", "which", "also", "such", "its", "their", "other", "these", "those", "into", "have", "has"}
# a line or sentence that opens with a provision label: "21 CFR 820.10(b)(1):", "- (b)(1)", "**820.10(c)**"
_LEAD_LABEL = re.compile(r"^\s*(?:[-*•]\s*|\d+\.\s+)?(?:\*\*)?\s*(?:21\s*C\.?F\.?R\.?\s*)?(?:§+\s*)?(?:\d{3,4}\.\d+)?\s*((?:\([a-z0-9]{1,4}\))+)", re.I)
NEAR_DUPLICATE = 0.7


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _found(text: str, needles: list[str]) -> bool:
    low = text.lower()
    return any(n.lower() in low for n in needles)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(_MARK.sub("", text.lower()))) - _STOP


def near_duplicates(answer: str) -> list[list[str]]:
    sentences = [s for s in split_sentences(answer) if len(_words(s)) >= 6]
    out = []
    for i in range(len(sentences)):
        for j in range(i + 1, len(sentences)):
            a, b = _words(sentences[i]), _words(sentences[j])
            if len(a & b) / len(a | b) >= NEAR_DUPLICATE:
                out.append([sentences[i][:120], sentences[j][:120]])
    return out


def provision_led_blocks(answer: str) -> list[str]:
    """Distinct paragraph labels that open a line: the evidence-by-evidence signature."""
    labels = []
    for line in re.split(r"\n+", answer):
        m = _LEAD_LABEL.match(line)
        if m and m.group(1) not in labels:
            labels.append(m.group(1))
    return labels


def shape_metrics(item: dict, rec: dict) -> dict:
    raw = rec.get("answer_raw") or ""
    final = rec.get("answer_final") or ""
    points = {p["name"]: _found(raw, p["any"]) for p in item["points"]}
    points_final = {p["name"]: _found(final, p["any"]) for p in item["points"]}
    quals = {q["name"]: _found(raw, q["any"]) for q in item["qualifiers"]}
    scope_hits = [t for t in item["out_of_scope"] if t.lower() in raw.lower()]
    shape = rec.get("answer_shape") or {}
    tokens = rec.get("tokens") or {}
    covered = sum(points.values())
    complete = covered == len(points)
    generated = tokens.get("generated")
    return {
        "shape": {
            "detected": {k: shape.get(k) for k in ("mode", "scope", "exhaustive")} if shape else None,
            "expected": {"mode": item["expected_mode"], "scope": item["expected_scope"], "exhaustive": item["expected_exhaustive"]},
            "mode_ok": (shape.get("mode") == item["expected_mode"]) if shape else None,
            "scope_ok": (shape.get("scope") == item["expected_scope"]) if shape else None,
            "exhaustive_ok": (shape.get("exhaustive") == item["expected_exhaustive"]) if shape else None,
        },
        "coverage": {"points": points, "covered": covered, "total": len(points), "complete": complete,
                     "missing": [k for k, v in points.items() if not v],
                     "covered_final": sum(points_final.values())},
        "qualifiers": {"present": quals, "missing": [k for k, v in quals.items() if not v]},
        "scope": {"out_of_scope_terms_found": scope_hits, "adherent": not scope_hits},
        "citations": {"citation_ok": (rec.get("citations") or {}).get("citation_ok"),
                      "distinct_markers": sorted({int(m) for m in _MARK.findall(raw)}),
                      "sentences": len(split_sentences(raw)),
                      "sentences_with_marker": sum(1 for s in split_sentences(raw) if _MARK.search(s))},
        "grounding": {"valid_raw": rec.get("valid_raw"), "valid_final": rec.get("valid_final"),
                      "status_raw": (rec.get("validation_initial") or {}).get("status"),
                      "codes_raw": (rec.get("validation_initial") or {}).get("codes"),
                      "repair": rec.get("repair"),
                      "claims": (rec.get("faithfulness") or {}).get("counts"),
                      "hallucination_raw": (rec.get("hallucination") or {}).get("any_raw")},
        "repetition": {"near_duplicate_pairs": near_duplicates(raw)},
        "dump": {"provision_led_blocks": provision_led_blocks(raw)},
        "tokens": {"generated": generated, "allowance": tokens.get("cap"), "finished": tokens.get("finished"),
                   "truncated": tokens.get("truncated"), "prompt": tokens.get("prompt_tokens"),
                   # Reported only for complete answers, so a short incomplete answer can never look "efficient".
                   "tokens_per_point_if_complete": round(generated / covered, 1) if complete and generated and covered else None},
        "latency_ms": {"generation": (rec.get("timings_ms") or {}).get("generation_ms"), "total": (rec.get("timings_ms") or {}).get("total_ms")},
    }


def summary_table(rows: list[dict]) -> str:
    head = ("| id | dimension | shape (detected) | shape ok | coverage | qualifiers missing | out-of-scope | citation ok | valid raw | "
            "repeats | led blocks | tokens | allowance | truncated | gen s |")
    lines = [head, "|" + "---|" * 15]
    for r in rows:
        m = r["metrics"]
        d = m["shape"]["detected"]
        det = f"{d['mode']}/{d['scope']}/{'exh' if d['exhaustive'] else 'non-exh'}" if d else "n/a (pre-Stage-12)"
        ok = m["shape"]
        okv = "n/a" if ok["mode_ok"] is None else ("yes" if ok["mode_ok"] and ok["scope_ok"] and ok["exhaustive_ok"] else "NO")
        gen = m["latency_ms"]["generation"]
        lines.append(" | ".join([
            f"| {r['id']}", r["dimension"], det, okv, f"{m['coverage']['covered']}/{m['coverage']['total']}",
            ", ".join(m["qualifiers"]["missing"]) or "none", ", ".join(m["scope"]["out_of_scope_terms_found"]) or "none",
            str(m["citations"]["citation_ok"]), str(m["grounding"]["valid_raw"]), str(len(m["repetition"]["near_duplicate_pairs"])),
            str(len(m["dump"]["provision_led_blocks"])), str(m["tokens"]["generated"]), str(m["tokens"]["allowance"]),
            str(m["tokens"]["truncated"]), f"{gen / 1000:.0f}" if gen else "-",
        ]) + " |")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument("--label", default="run")
    p.add_argument("--ids", nargs="*", default=None)
    p.add_argument("--answer-shape", choices=("adaptive", "off"), default=None,
                   help="override RagConfig.answer_shape (Stage 12 code only)")
    p.add_argument("--out-root", type=Path, default=OUT_ROOT)
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    items = [i for i in load(args.dataset) if not args.ids or i["id"] in args.ids]
    settings = load_settings()
    config = evaluation_rag_config(settings)
    if args.answer_shape is not None:
        if not hasattr(config, "answer_shape"):
            raise SystemExit("this code has no answer_shape setting")
        config = replace(config, answer_shape=args.answer_shape)
    out_dir = args.out_root / f"{args.label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)

    db = Database.from_env()
    db.connect()
    if str(db.status().get("default_transaction_read_only", "")).lower() not in ("on", "true", "1"):
        raise SystemExit("database connection is not read-only")
    settings.generation = configured_generation_config(settings)
    t0 = time.perf_counter()
    generator = load_qwen_generator(settings, local_files_only=True)
    print(f"model loaded in {time.perf_counter() - t0:.1f}s; config answer_shape={getattr(config, 'answer_shape', 'n/a')}", flush=True)
    pipeline = RagPipeline(LexicalRetriever(db), generator, config)

    rows = []
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for item in items:
            ex = Stage5Example(id=item["id"], category=item["category"], question=item["question"], expected_requirements=(),
                               expected_exact=(), expected_missing=(), expected_behavior="answer", expected_terms=(), domain="regulatory")
            t1 = time.perf_counter()
            rec = run_full(ex, pipeline)
            row = {"id": item["id"], "dimension": item["dimension"], "question": item["question"],
                   "answer_raw": rec.get("answer_raw"), "answer_final": rec.get("answer_final"),
                   "answer_shape": rec.get("answer_shape"), "evidence_plan": rec.get("evidence_plan"),
                   "shape_validation": ((rec.get("validation_initial") or {}).get("shape")),
                   "legacy_shape": rec.get("shape"), "selected_ids": rec.get("selected_ids"),
                   "metrics": shape_metrics(item, rec), "wall_s": round(time.perf_counter() - t1, 1)}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            rows.append(row)
            m = row["metrics"]
            print(f"{item['id']} {item['dimension']}: coverage {m['coverage']['covered']}/{m['coverage']['total']} "
                  f"tokens {m['tokens']['generated']} ({row['wall_s']}s)", flush=True)
    db.close()
    (out_dir / "summary.md").write_text(
        f"# Answer-shape evaluation: {args.label}\n\ndataset: {args.dataset.name}\n"
        f"config answer_shape: {getattr(config, 'answer_shape', 'n/a (pre-Stage-12 code)')}\n\n{summary_table(rows)}\n",
        encoding="utf-8")
    print(f"\nwrote {out_dir}")
    print(summary_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
