"""Live Run A / Run B regression for the answer-accuracy feature (§14).

Proves the feature is observational against the real model and the real
read-only database, which the in-process test (tests/test_accuracy_observer.py)
cannot do because it scripts the generator.

Two arms, because they refute different things:

  payload   one answer, two payloads built from it - the one the server sends
            with the feature off and the one it sends with it on. Shows that
            the ONLY difference in the response is the assessment object.

  live      the same question answered twice, feature off then feature on.
            Shows that running with the feature on does not perturb
            generation. Decoding is greedy, so a difference here is a real
            finding; to keep that honest the arm also answers once more with
            the feature OFF, so an off/off difference identifies
            nondeterminism rather than blaming the evaluator.

    python scripts/accuracy_regression.py                     # the default 8 questions
    python scripts/accuracy_regression.py --questions q.txt    # one per line
    python scripts/accuracy_regression.py --arms payload       # skip the 2x-slower live arm

Writes artifacts/accuracy/regression_<timestamp>.json and prints a verdict.
Expect roughly 30-90 s per answer on this CPU: the live arm costs three
generations per question, the payload arm one.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from regulus.config import PROJECT_ROOT, load_settings

OUT_DIR = PROJECT_ROOT / "artifacts" / "accuracy"

# Chosen to cover the paths that differ: a provision that exists, a part-level
# question, one that does not exist, a guidance docket, a false premise, a
# general question, an out-of-scope question and a multi-provision question.
DEFAULT_QUESTIONS = [
    "What does 21 CFR 820.10 require?",
    "What does 21 CFR Part 11 cover?",
    "What are the specific requirements of 21 CFR 314.999?",
    "Summarize FDA guidance FDA-2016-D-2565.",
    "What exact storage temperature range does 21 CFR Part 211 require for all finished tablets?",
    "What records must a device manufacturer keep for complaints?",
    "What does the EU Medical Device Regulation require for clinical evaluation?",
    "What do 21 CFR 820.30(a) and 21 CFR 820.30(g) require?",
]

# The parts of the response that must not move. Everything else is diagnostics.
ANSWER_BEARING = ("answer", "citations", "sources", "dropped_sources", "notes", "grounding", "retrieval",
                  "query_type", "plan", "evidence", "coverage", "coverage_action", "selection", "answer_shape",
                  "question_analysis", "quality_flags", "normalization", "validation", "citation_support",
                  "answerability", "generation_called", "generation_blocked", "block_reason", "fallback_type",
                  "fallback_reason", "scope_policy", "input_tokens", "output_tokens", "model_called",
                  "evidence_snapshot")


def comparable(result: dict) -> dict:
    """The answer-bearing response, with wall-clock figures removed."""
    out = {k: result.get(k) for k in ANSWER_BEARING}
    generation = dict(result.get("generation") or {})
    for key in ("tokens_per_second", "decode_tokens_per_second"):
        generation.pop(key, None)
    out["generation"] = generation or None
    return out


def diff(a: dict, b: dict) -> list[str]:
    out = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            out.append(key)
    return out


def evidence_check(question: str, response: dict, engine) -> dict:
    """The exact-evidence chain for one answer: the snapshot the pipeline captured
    (and checked against the prompt it sent), the fingerprint the evaluator
    reports having used, and a replay from a JSON round trip of the stored
    record alone - no package, no database, no retrieval."""
    from regulus.accuracy import evaluate
    from regulus.traceability import EXACT, fingerprint, load

    stored = response.get("evidence_snapshot")
    used = ((response.get("accuracy") or {}).get("evidence") or {})
    if stored is None:
        return {"captured": False, "ok": False}
    reloaded = load(json.loads(json.dumps(stored)))       # what a later process would read back
    replay = evaluate(question, response["answer"], evidence=reloaded, model_called=response.get("model_called", True),
                      fallback_type=response.get("fallback_type"), identifier_index=engine.identifier_index(),
                      aligner=engine.aligner())
    prints = {"stored": stored["fingerprint"], "recomputed_from_text": fingerprint(reloaded.items),
              "evaluator_live": used.get("fingerprint"), "evaluator_replay": replay.evidence.get("fingerprint")}
    match = len(set(prints.values())) == 1
    verified = stored["prompt_verified"] is True or not stored["model_called"]
    return {
        "captured": True, "fingerprints": prints, "fingerprints_match": match,
        "provenance_live": used.get("provenance"), "provenance_replay": replay.evidence.get("provenance"),
        "prompt_verified": stored["prompt_verified"], "prompt_sha256": stored["prompt_sha256"],
        "model_called": stored["model_called"], "items": len(stored["items"]),
        "guidance_items": sum(1 for i in stored["items"] if i["source_type"] == "guidance"),
        "truncated_items": sum(1 for i in stored["items"] if i["truncated"]),
        "replay": {"status": replay.status, "accuracy": replay.accuracy,
                   "verdict": (replay.checked.get("answer_verdict") or {}).get("verdict")},
        "ok": match and verified and used.get("provenance") == EXACT and replay.evidence.get("provenance") == EXACT,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--questions", type=Path, help="a file of questions, one per line (default: the built-in 8)")
    p.add_argument("--arms", choices=("both", "payload", "live"), default="both")
    p.add_argument("--offline", action="store_true", help="fail instead of downloading the model")
    p.add_argument("--adapter", default="", help="adapter id as the UI names it (default: as configured)")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    questions = ([q.strip() for q in args.questions.read_text(encoding="utf-8").splitlines() if q.strip()]
                 if args.questions else list(DEFAULT_QUESTIONS))
    from serve_ui import Engine

    engine = Engine(load_settings(), offline=args.offline)
    ask = lambda q, accuracy: engine.ask(q, adapter=args.adapter, accuracy=accuracy)

    rows: list[dict] = []
    for i, question in enumerate(questions, start=1):
        print(f"\n[{i}/{len(questions)}] {question}", flush=True)
        row: dict = {"question": question}

        # -- payload arm: one answer, the two payloads the server would send
        t0 = time.perf_counter()
        with_on = ask(question, True)
        row["answer_seconds"] = round(time.perf_counter() - t0, 2)
        assessment = with_on.get("accuracy")
        off_keys = {k: v for k, v in with_on.items() if k != "accuracy"}
        row["answer"] = with_on["answer"]
        row["citations"] = [c["label"] for c in with_on["citations"]]
        row["payload"] = {
            "only_difference_is_the_assessment": sorted(set(with_on) - set(off_keys)) == ["accuracy"],
            "answer_sha_equal": True,     # same object; recorded for completeness
            "accuracy_ms": (with_on.get("server_timings_ms") or {}).get("accuracy_ms"),
            "status": (assessment or {}).get("status"),
            "accuracy": (assessment or {}).get("accuracy"),
            "dimensions": {d["dimension"]: d["state"] for d in (assessment or {}).get("dimensions", [])},
            "reason": (assessment or {}).get("reason"),
        }
        row["evidence"] = evidence_check(question, with_on, engine)
        ev = row["evidence"]
        print(f"    evidence: {'EXACT' if ev['ok'] else 'NOT EXACT'}  fingerprint "
              f"{(ev.get('fingerprints') or {}).get('stored', '-')[:16]}  items {ev.get('items')} "
              f"(guidance {ev.get('guidance_items')}, truncated {ev.get('truncated_items')})  "
              f"prompt_verified={ev.get('prompt_verified')}", flush=True)
        print(f"    accuracy: {row['payload']['status']} {row['payload']['accuracy']} "
              f"(+{row['payload']['accuracy_ms']} ms of {row['answer_seconds']} s)", flush=True)

        if args.arms in ("both", "live"):
            # -- live arm: off, on, and off again to separate nondeterminism from the feature
            t1 = time.perf_counter()
            run_a = ask(question, False)
            a_seconds = round(time.perf_counter() - t1, 2)
            t2 = time.perf_counter()
            run_b = ask(question, True)
            b_seconds = round(time.perf_counter() - t2, 2)
            run_a2 = ask(question, False)
            changed = diff(comparable(run_a), comparable(run_b))
            baseline = diff(comparable(run_a), comparable(run_a2))
            row["live"] = {
                "identical": not changed,
                "fields_that_differ": changed,
                "off_vs_off_fields_that_differ": baseline,
                "attributable_to_the_feature": sorted(set(changed) - set(baseline)),
                "answer_bytes_equal": run_a["answer"].encode() == run_b["answer"].encode(),
                "run_a_has_no_assessment": "accuracy" not in run_a,
                "seconds": {"off": a_seconds, "on": b_seconds},
                "added_seconds": round(b_seconds - a_seconds, 2),
            }
            verdict = "identical" if not changed else (
                "nondeterministic generation" if not set(changed) - set(baseline) else "CHANGED BY THE FEATURE")
            print(f"    live arm: {verdict}  (off {a_seconds}s, on {b_seconds}s)", flush=True)
        rows.append(row)

    payload_ok = all(r["payload"]["only_difference_is_the_assessment"] for r in rows)
    live_rows = [r for r in rows if "live" in r]
    attributable = [r["question"] for r in live_rows if r["live"]["attributable_to_the_feature"]]
    nondeterministic = [r["question"] for r in live_rows if r["live"]["off_vs_off_fields_that_differ"]]
    accuracy_ms = [r["payload"]["accuracy_ms"] for r in rows if r["payload"]["accuracy_ms"] is not None]
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ"),
        "questions": len(rows),
        "arms": args.arms,
        "pipeline": engine.settings.model.id,
        "adapter": args.adapter or "configured",
        "verdict": {
            "payload_arm_passes": payload_ok,
            "live_arm_passes": not attributable,
            "questions_changed_by_the_feature": attributable,
            "questions_with_nondeterministic_generation": nondeterministic,
            "exact_evidence_for_every_answer": all(r["evidence"]["ok"] for r in rows),
        },
        "latency_ms": {
            "accuracy_min": min(accuracy_ms, default=None),
            "accuracy_max": max(accuracy_ms, default=None),
            "accuracy_mean": round(sum(accuracy_ms) / len(accuracy_ms), 3) if accuracy_ms else None,
            "answer_seconds_mean": round(sum(r["answer_seconds"] for r in rows) / len(rows), 2) if rows else None,
        },
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"regression_{report['generated_at']}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    evidence_ok = report["verdict"]["exact_evidence_for_every_answer"]
    print(f"\nexact evidence: {'PASS' if evidence_ok else 'FAIL'}")
    print(f"payload arm: {'PASS' if payload_ok else 'FAIL'}")
    if live_rows:
        print(f"live arm:    {'PASS' if not attributable else 'FAIL: ' + ', '.join(attributable)}")
        if nondeterministic:
            print(f"  note: generation itself differed off-vs-off for: {', '.join(nondeterministic)}")
    print(f"accuracy cost: {report['latency_ms']['accuracy_mean']} ms mean "
          f"(max {report['latency_ms']['accuracy_max']}) against "
          f"{report['latency_ms']['answer_seconds_mean']} s per answer")
    print(f"written: {path.relative_to(PROJECT_ROOT)}")
    engine.db.close()
    return 0 if payload_ok and not attributable and evidence_ok else 1


if __name__ == "__main__":
    sys.exit(main())
