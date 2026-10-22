"""Score the Fix B measurement against PREREGISTRATION.md (no database, no model). Writes evaluation.json."""
import json
from collections import Counter
from pathlib import Path

D = Path(__file__).resolve().parents[1]
ROOT = D.parents[1]
raw = json.loads((D / "raw.json").read_text())
Q = raw["q100"]
load = lambda p: {json.loads(l)["id"]: json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()}
B352 = load(ROOT / "data/evaluation/results/retrieval_baseline_20261021T102326Z_16fa796d/per_question.jsonl")
gen = {q: r for q, r in Q.items() if r["general"]}


def tally(c):
    return {"candidates": sum(v["candidate"] for r in gen.values() for v in r[c]["required"].values()),
            "in_context": sum(v["in_context"] for r in gen.values() for v in r[c]["required"].values()),
            "of": sum(len(r[c]["required"]) for r in gen.values())}


out = {"base": tally("base")}
for c in ("F1", "F2"):
    cg, cl, fg, fl, surv = [], [], [], [], Counter()
    g_removed, e_removed = [], []
    for q, r in Q.items():
        for lab, v in r[c]["required"].items():
            b = r["base"]["required"][lab]
            if v["candidate"] and not b["candidate"]:
                cg.append(f"{q} {lab}")
                surv["reached context" if v["in_context"] else f"dropped: {v['drop_reason'] or 'not selected'}"] += 1
            if b["candidate"] and not v["candidate"]: cl.append(f"{q} {lab}")
            if v["in_context"] and not b["in_context"]: fg.append(f"{q} {lab}")
            if b["in_context"] and not v["in_context"]: fl.append(f"{q} {lab}")
        bk = {s[2]: s for s in r["base"]["sources"]}; vk = {s[2] for s in r[c]["sources"]}
        for k, s in bk.items():
            if k in vk: continue
            if s[1] != "ecfr": g_removed.append(f"{q} {s[0][:70]}")
            else:
                still = all(r[c]["required"][lab]["in_context"] for lab in r[c]["required"] if r["base"]["required"][lab]["in_context"])
                e_removed.append({"q": q, "row": s[0], "required_still_in_context": still})
    rec = load(D / "runs_352" / f"{c}.jsonl")
    t = Counter(); lost, gained = [], []
    for k, a in B352.items():
        ta = {x["target"]: x for x in a.get("targets") or []}
        tb = {x["target"]: x for x in rec[k].get("targets") or []}
        for name, x in ta.items():
            y = tb.get(name, {})
            if x.get("candidate_rank") is None and y.get("candidate_rank") is not None: t["candidate gained"] += 1
            if x.get("candidate_rank") is not None and y.get("candidate_rank") is None: t["candidate lost"] += 1
            if not x.get("in_context") and y.get("in_context"): gained.append((k, name))
            if x.get("in_context") and not y.get("in_context"): lost.append((k, name, y.get("drop_reasons")))
    base_ctx = sum(1 for a in B352.values() for x in a.get("targets") or [] if x.get("in_context"))
    var_ctx = sum(1 for a in rec.values() for x in a.get("targets") or [] if x.get("in_context"))
    e_bad = [x for x in e_removed if not x["required_still_in_context"]]
    res = {"q100": {**tally(c), "candidate_gained": cg, "candidate_lost": cl, "context_gained": fg, "context_lost": fl,
                    "fate_of_new_candidates": dict(surv), "guidance_removed": g_removed, "ecfr_rows_removed": e_removed},
           "s352": {"targets_in_context_base": base_ctx, "targets_in_context_variant": var_ctx, **dict(t),
                    "context_gained": gained, "context_lost": lost}}
    res["criteria"] = {"B1": len(fg) >= 3 and not fl, "B2": not lost and var_ctx >= base_ctx, "B3": not g_removed, "B4": not e_bad}
    res["verdict"] = ("WORTH A CODE EXPERIMENT" if all(res["criteria"].values()) else
                      "CANDIDATES ONLY" if cg or t["candidate gained"] else "NO GAIN")
    out[c] = res
(D / "evaluation.json").write_text(json.dumps(out, indent=1))
print("base", out["base"])
for c in ("F1", "F2"):
    v = out[c]; q = v["q100"]; s = v["s352"]
    print(f"{c}: {v['verdict']} | criteria {v['criteria']}")
    print(f"   100: candidates {q['candidates']} (+{len(q['candidate_gained'])}/-{len(q['candidate_lost'])}) | in context {q['in_context']} (+{len(q['context_gained'])}/-{len(q['context_lost'])}) of {q['of']} | new-candidate fate {q['fate_of_new_candidates']}")
    print(f"   100: context gained {q['context_gained']} lost {q['context_lost']} | guidance removed {len(q['guidance_removed'])} | eCFR rows removed {len(q['ecfr_rows_removed'])}")
    print(f"   352: targets in context {s['targets_in_context_base']} -> {s['targets_in_context_variant']} | candidate +{s.get('candidate gained', 0)}/-{s.get('candidate lost', 0)} | gained {s['context_gained']} | lost {s['context_lost']}")
