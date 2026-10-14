"""Evaluate a UI measurement session offline (regulus.evaluation.ui_sessions).

    python scripts/evaluate_ui_session.py data/ui_measurements/<session> [--evaluation-out FILE]
                                                                         [--offline-aligner lexical|semantic]

Loads no answering model and no database, answers nothing, and only reads the session's files. Results go
to a new file, by default <session>/evaluations/<utc>_<execution id>.jsonl (git-ignored, like the session).
`--offline-aligner semantic` loads the UI's pinned local embedder and fails rather than fall back.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regulus.evaluation.offline_evaluation import semantic_aligner  # noqa: E402
from regulus.evaluation.ui_sessions import NotASession, evaluate_ui_session  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_dir")
    ap.add_argument("--evaluation-out", default=None, metavar="FILE", help="the new results file (refused if it exists)")
    ap.add_argument("--offline-aligner", choices=("lexical", "semantic"), default="lexical")
    args = ap.parse_args(argv)
    try:
        summary = evaluate_ui_session(Path(args.session_dir), args.evaluation_out, root=ROOT,
                                      aligner=semantic_aligner() if args.offline_aligner == "semantic" else None)
    except NotASession as exc:
        print(f"STOP: {exc}")
        return 2
    print(json.dumps(summary, indent=1))
    return 0 if summary["session_files_only_appended"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
