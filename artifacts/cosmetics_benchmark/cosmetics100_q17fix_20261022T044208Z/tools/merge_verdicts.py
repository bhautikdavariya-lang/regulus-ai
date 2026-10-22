"""Merge scoring/batch_*.json and scoring/fabrication_review.json into scoring/verdicts.json (one entry per selected ID)."""
import json, sys
from pathlib import Path
run = Path(sys.argv[1]).resolve()
sc = run / "scoring"
v = {}
for p in sorted(sc.glob("batch_*.json")):
    for k, x in json.loads(p.read_text(encoding="utf-8")).items():
        if k in v:
            raise SystemExit(f"duplicate verdict {k} in {p.name}")
        v[k] = x
fab = json.loads((sc / "fabrication_review.json").read_text(encoding="utf-8"))["fab_1"]
for k, note in fab.items():
    v[k]["fab"] = 1
    v[k]["why"] += f" Fabricated = 1 (bank Instructions rule 3, invented requirement): {note}"
ids = json.loads((run / "selection.json").read_text(encoding="utf-8"))["summary"]["selected_ids"]
missing, extra = [i for i in ids if i not in v], [k for k in v if k not in ids]
if missing or extra:
    raise SystemExit(f"missing {missing} extra {extra}")
for k, x in v.items():
    assert x["ce"] in (0, 1) and x["fab"] in (0, 1) and x["sub"] in (0, 1, 2) and x["comp"] in (0, 1, 2) and x["scope"] in (0, 1), k
(sc / "verdicts.json").write_text(json.dumps({i: v[i] for i in ids}, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(v), "verdicts;", sum(x["fab"] for x in v.values()), "fabricated")
