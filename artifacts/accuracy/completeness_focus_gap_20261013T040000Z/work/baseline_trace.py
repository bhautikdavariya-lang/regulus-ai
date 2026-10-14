"""Step 1: the failure on the production package, with the REAL _focus_gap inputs explained."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from harness import _STATE, completeness, evaluate, focus_gap_rule, recording_rule  # noqa: E402

Q = "What is the reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR 312.32?"
LIVE = ("The reporting deadline for an unexpected fatal or life-threatening suspected adverse reaction under 21 CFR "
        "312.32 is no later than 7 calendar days after the sponsor's initial receipt of the information [9].")

for rule in ("production", "distinguishing"):
    store = []
    with focus_gap_rule(recording_rule(store, rule)):
        a = evaluate(Q, LIVE)
    print(f"===== rule={rule}: verdict={a.to_dict()['answer_verdict']['verdict']} accuracy={a.to_dict()['accuracy']}")
    print("   completeness:", completeness(a))
    for row in store[-1]["trace"]:
        print("  ", json.dumps(row))
_STATE["db"].close()
