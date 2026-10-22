"""Every acceptance criterion of DECISION_RECORD.md §4.5, from the saved replays (read-only; writes runs/evaluation.json).

    python evaluate_switch.py <decision_dir>

Inputs: runs/C1_off_cosmetics.jsonl, runs/C2_on_cosmetics.jsonl (100 cosmetics), runs/P1_off_352, runs/P2_on_352,
the cosmetics key (Step 6 selection.json) and the 352-set targets recorded by the harness.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

D = Path(sys.argv[1]).resolve()
ROOT = D.parents[2]
SEL = {q["ID"]: q for q in json.loads((ROOT / "artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z/arm_A_switch_off/selection.json")
                                      .read_text(encoding="utf-8"))["questions"]}
PART73 = ["COS-73.2085-Q1", "COS-73.2095-Q1", "COS-73.2250-Q1", "COS-73.2298-Q1", "COS-73.2575-Q1", "COS-73.2645-Q1",
          "COS-73.2646-Q1", "COS-73.2647-Q1", "COS-73.2725-Q1"]
SEC = re.compile(r"\b(\d{2,3}\.\d+[a-z]?)\b")
OR = re.compile(r"(?<![\w/-])or(?![\w/-])", re.I)


def load(p):
    return {r["id"]: r for r in (json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip())}


def sec_of(citation):
    m = re.match(r"21 CFR (\d+\.\d+[a-z]?)((?:\([^)]+\))*)$", citation or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def key_paragraphs(q):
    """Section -> required top-level paragraphs from the key ('(a), (b)', '(a)-(e)'); empty set = whole section."""
    text = str(q["Expected Citation — VERIFIED KEY"])
    out = {}
    for m in re.finditer(r"(\d{2,3}\.\d+[a-z]?)((?:\s*\([a-z0-9]+\)(?:\s*[-–]\s*\([a-z0-9]+\))?\s*,?)*)", text):
        paras = set()
        for a, b in re.findall(r"\(([a-z])\)(?:\s*[-–]\s*\(([a-z])\))?", m.group(2)):
            paras |= {chr(c) for c in range(ord(a), ord(b or a) + 1)}
        out.setdefault(m.group(1), set()).update(paras)
    return out


def cos_view(rec, q):
    exp = key_paragraphs(q)
    ecfr = [s for s in rec["sources"] if (s[0] or "").startswith("21 CFR")]
    first_rank = first_cit = None
    para_hit = False
    for n, s in enumerate(ecfr, 1):
        sec, path = sec_of(s[0])
        if sec in exp:
            if first_rank is None:
                first_rank, first_cit = n, s[0]
            top = re.match(r"\(([a-z])\)", path or "")
            if not exp[sec] or (top and top.group(1) in exp[sec]) or not path:
                para_hit = True
    dropped_key = [d for d in rec["dropped"] if sec_of(d[0])[0] in exp]
    return {"key": str(q["Expected Citation — VERIFIED KEY"]), "in_context": first_rank is not None, "first_rank": first_rank,
            "first_citation": first_cit, "required_paragraph_in_context": para_hit,
            "rows_1271_90": sum("1271.90" in (s[0] or "") for s in rec["sources"]),
            "key_rows_dropped": dropped_key, "prompt": [s[0] for s in rec["sources"]],
            "section_coverage": (rec.get("retrieval") or {}).get("section_coverage")}


def cosmetics():
    off, on = load(D / "runs/C1_off_cosmetics.jsonl"), load(D / "runs/C2_on_cosmetics.jsonl")
    changed = sorted(i for i in on if on[i]["sources"] != off[i]["sources"] or on[i]["dropped"] != off[i]["dropped"])
    views = {i: {"off": cos_view(off[i], SEL[i]), "on": cos_view(on[i], SEL[i])} for i in on}
    had = sorted(i for i in views if views[i]["off"]["in_context"])
    p73 = {i: views[i]["on"] for i in PART73}
    passing73 = sorted(i for i, v in p73.items() if v["in_context"] and v["first_rank"] <= 4)
    return {
        "changed_questions": changed,
        "changed_all_contain_standalone_or": all(OR.search(SEL[i]["Question (ask verbatim)"]) for i in changed),
        "part73": p73,
        "criterion_part73_7_of_9": {"threshold": 7, "met": len(passing73), "questions_met": passing73,
                                    "questions_failed": sorted(set(PART73) - set(passing73)), "passed": len(passing73) >= 7},
        "criterion_no_1271_90_in_part73": {"rows": {i: v["rows_1271_90"] for i, v in p73.items()},
                                           "passed": all(v["rows_1271_90"] == 0 for v in p73.values())},
        "criterion_28_keep_key_section": {"had_off": len(had), "lost_on": sorted(i for i in had if not views[i]["on"]["in_context"]),
                                          "passed": all(views[i]["on"]["in_context"] for i in had)},
        "criterion_changes_only_or_questions": {"passed": all(OR.search(SEL[i]["Question (ask verbatim)"]) for i in changed)},
        "key_section_in_context_off_on": [len(had), sum(v["on"]["in_context"] for v in views.values())],
        "required_paragraph_in_context_off_on": [sum(v["off"]["required_paragraph_in_context"] for v in views.values()),
                                                 sum(v["on"]["required_paragraph_in_context"] for v in views.values())],
    }


def hits(rec):
    """Section-level and provision-level: is any expected target in the final context?"""
    sec = any(t["in_context"] for t in rec["targets"] if t["level"] == "section" or t["kind"] == "section")
    prov = any(t["in_context"] for t in rec["targets"] if t["level"] == "provision")
    return sec, prov


def set352():
    off, on = load(D / "runs/P1_off_352/per_question.jsonl"), load(D / "runs/P2_on_352/per_question.jsonl")
    volatile = {"timings"}
    norm = lambda r: json.dumps({k: v for k, v in r.items() if k not in volatile}, sort_keys=True, default=str)
    changed = sorted(i for i in on if norm(on[i]) != norm(off[i]))
    by_cat_off, by_cat_on, by_cls_off, by_cls_on, n_cat, n_cls = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    lost, gained, prov_lost, prov_gained = [], [], [], []
    for i in on:
        if not on[i]["targets"]:
            continue
        so, po = hits(off[i])
        sn, pn = hits(on[i])
        cat, cls = on[i]["category"], on[i]["question_class"]
        n_cat[cat] += 1; n_cls[cls] += 1
        by_cat_off[cat] += so; by_cat_on[cat] += sn; by_cls_off[cls] += so; by_cls_on[cls] += sn
        if so and not sn: lost.append(i)
        if sn and not so: gained.append(i)
        if po and not pn: prov_lost.append(i)
        if pn and not po: prov_gained.append(i)
    s_off = json.loads((D / "runs/P1_off_352/summary.json").read_text())
    s_on = json.loads((D / "runs/P2_on_352/summary.json").read_text())
    cats = sorted(n_cat)
    return {
        "changed_ids": changed,
        "changed_detail": {i: {"question": on[i]["question"], "category": on[i]["category"], "class": on[i]["question_class"],
                               "contains_or": bool(OR.search(on[i]["question"])), "section_hit_off_on": [hits(off[i])[0], hits(on[i])[0]],
                               "provision_hit_off_on": [hits(off[i])[1], hits(on[i])[1]],
                               "negative_control": on[i]["is_negative_control"]} for i in changed},
        "section_in_context_by_class": {c: [by_cls_off[c], by_cls_on[c], n_cls[c]] for c in sorted(n_cls)},
        "section_in_context_by_category": {c: [by_cat_off[c], by_cat_on[c], n_cat[c]] for c in cats},
        "criterion_overall_recall_not_lower": {"off": sum(by_cls_off.values()), "on": sum(by_cls_on.values()),
                                               "passed": sum(by_cls_on.values()) >= sum(by_cls_off.values())},
        "criterion_no_category_lower": {"lower": [c for c in cats if by_cat_on[c] < by_cat_off[c]],
                                        "passed": all(by_cat_on[c] >= by_cat_off[c] for c in cats)},
        "criterion_identifier_unchanged": {"changed_identifier": [i for i in changed if on[i]["question_class"] != "plain_language"],
                                           "passed": all(on[i]["question_class"] == "plain_language" for i in changed)},
        "criterion_negative_controls_unchanged": {"passed": s_on["negative_controls"] == s_off["negative_controls"]},
        "section_lost": lost, "section_gained": gained, "provision_lost": prov_lost, "provision_gained": prov_gained,
        "summary_any_in_context": {g: [s_off["metrics"][g]["section_level"]["any_in_context"]["count"],
                                       s_on["metrics"][g]["section_level"]["any_in_context"]["count"]]
                                   for g in ("all", "identifier", "plain_language")},
        "changes_only_or_questions": all(OR.search(on[i]["question"]) for i in changed),
    }


out = {"cosmetics": cosmetics(), "set352": set352()}
(D / "runs/evaluation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
