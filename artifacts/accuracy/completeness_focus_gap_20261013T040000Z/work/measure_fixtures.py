"""Fixtures under three configurations: production, focus-gap candidate only, both candidates."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from candidate import patched  # noqa: E402
from fixtures import CASES  # noqa: E402
from harness import _STATE, completeness, evaluate  # noqa: E402
import contextlib

CONFIGS = {"production": contextlib.nullcontext, "focus_only": lambda: patched(anchor=False), "both": patched}


def label(a):
    from regulus.accuracy.review import question_review
    return question_review(a.to_dict(), question=a.to_dict()["checked"]["question"])["label"]


def main():
    rows = []
    for cid, q, build, expect in CASES:
        answer = build()
        res = {"id": cid, "expect": expect}
        for name, ctx in CONFIGS.items():
            with ctx():
                a = evaluate(q, answer)
            d = a.to_dict(); st, det = completeness(a)
            res[name] = {"label": label(a), "score": d["accuracy"], "completeness": st, "verdict": d["answer_verdict"]["verdict"],
                         "detail": det, "claims": [(c["support"], c.get("support_basis")) for c in a.checked["claims"]]}
        rows.append(res)
        print(f"{cid:<24} expect={expect:<17} " + "  ".join(
            f"{n}={res[n]['label'][:4]:<4}{str(res[n]['score']):<4}" for n in CONFIGS), flush=True)
    Path(sys.argv[1]).write_text(json.dumps(rows, indent=1, default=str))
    _STATE["db"].close()


if __name__ == "__main__":
    main()
