"""Write `docs/model_dashboard_metrics.md` from the metric registry.

    python scripts/generate_metric_docs.py
    python scripts/generate_metric_docs.py --check    # fail if the file is stale

The document and the dashboard's ⓘ tooltips are generated from the same
`MetricDefinition` records, so the two cannot drift apart. Editing the
document by hand is pointless: run this instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from regulus.dashboard import metrics as M  # noqa: E402

OUT = ROOT / "docs" / "model_dashboard_metrics.md"

DIRECTION = {
    "higher_is_better": "higher is better",
    "lower_is_better": "lower is better",
    "informational": "informational — neither direction is better",
}

HEADER = """# Regulus AI: metric reference

Every number the model evaluation dashboard shows is defined here. This file
is **generated** from `src/regulus/dashboard/metrics.py` by
`python scripts/generate_metric_docs.py`; the dashboard's ⓘ tooltips are
rendered from the same records, so the two cannot disagree. Do not edit it by
hand.

Three things are true of every entry:

* **A definition is not a judgment.** Each metric says what it measures and,
  just as importantly, what it does not prove. The caveat is part of the
  metric, not a footnote.
* **Direction is declared, never inferred.** A number going up is an
  improvement only where this file says higher is better.
* **Heuristics are labelled.** A metric marked HEURISTIC is an approximation
  with known failure modes, and the dashboard shows that badge beside it.

There is deliberately no composite score. Metrics move in different
directions for different reasons, and one number would hide which.

"""

FOOTER = """
## Reading these together

A few pairings matter more than any single figure.

* **Raw against final.** `valid_raw` and `correctness_raw` describe the
  model. `valid_final` and `correctness_final` describe the product after the
  deterministic repair layer has run. `correct_only_after_repair` is the
  honest size of the gap between them. A rise in the final figure that is
  entirely that count is not model improvement.
* **The full pipeline against exact evidence only.** `valid_raw` and
  `valid_raw_controlled` answer different questions: the first asks whether
  the system works, the second whether the model can work when the evidence
  is perfect. A failure in both is the model; a failure only in the first is
  the context.
* **Repair frequency beside raw validation.** A low `repair_rate` is good
  only when `valid_raw` is high. Low repair with low raw validation means
  problems are going out unrepaired.
* **Training loss against nothing at all.** `final_train_loss` and
  `final_eval_loss` belong to the training process. They are never evidence
  that answers improved; only an evaluation run on a benchmark can show that.
"""


def render() -> str:
    parts = [HEADER]
    parts.append("## Index\n")
    for family in M.FAMILY_ORDER:
        rows = [d for d in M.all_definitions() if d.family == family]
        if not rows:
            continue
        names = ", ".join(f"[{d.name}](#{_anchor(d.name)})" for d in rows)
        parts.append(f"* **{M.FAMILY_TITLES[family]}** — {names}\n")
    parts.append("")

    for family in M.FAMILY_ORDER:
        rows = [d for d in M.all_definitions() if d.family == family]
        if not rows:
            continue
        parts.append(f"## {M.FAMILY_TITLES[family]}\n")
        for d in rows:
            parts.append(f"### {d.name}\n")
            parts.append(f"`{d.key}`{'  ·  **HEURISTIC**' if d.heuristic else ''}\n")
            parts.append(f"{d.definition}\n")
            parts.append(f"| | |\n|---|---|\n"
                         f"| Calculation | {d.calculation} |\n"
                         f"| Direction | {DIRECTION.get(d.direction, d.direction)} |\n"
                         f"| Unit | {d.unit} |\n"
                         f"| Read from | `{d.source_hint or 'not recorded'}` |\n")
            if d.caveats:
                parts.append(f"**What it does not prove.** {d.caveats}\n")
    parts.append(FOOTER)
    parts.append(f"\n---\n\n{len(M.all_definitions())} metrics across "
                 f"{len([f for f in M.FAMILY_ORDER if any(d.family == f for d in M.all_definitions())])} families.\n")
    return "\n".join(parts)


def _anchor(name: str) -> str:
    return "".join(c for c in name.lower().replace(" ", "-") if c.isalnum() or c == "-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero if the file is out of date")
    args = parser.parse_args()

    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is out of date; run python scripts/generate_metric_docs.py")
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(M.all_definitions())} metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
