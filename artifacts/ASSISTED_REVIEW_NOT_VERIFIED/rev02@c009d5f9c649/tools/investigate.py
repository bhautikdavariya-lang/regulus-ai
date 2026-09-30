"""ASSISTED REVIEW — NOT VERIFIED — benchmark-integrity investigation (read-only).

Computes the systematic-finding tables mechanically over all 300 rows from the
evidence already in this package, the frozen baseline, and (read-only) the
eCFR snapshot and the platform's own rubric/failure-rule tables.
Writes only under ./integrity_investigation/.

    python -u tools/investigate.py
"""

from __future__ import annotations

import csv
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
ROOT = PKG.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from regulus.retrieval import Database  # noqa: E402
from regulus.retrieval.references import parse_cfr_references  # noqa: E402

OUT = PKG / "integrity_investigation"
OUT.mkdir(exist_ok=True)
LABEL = "ASSISTED REVIEW — NOT VERIFIED (integrity investigation; read-only; no key changed)"

ev = {json.loads(l)["question_id"]: json.loads(l)
      for l in (PKG / "evidence" / "evidence_all.jsonl").read_text(encoding="utf-8").splitlines()}
prop = {json.loads(l)["question_id"]: json.loads(l)
        for l in (PKG / "02_proposals_full.jsonl").read_text(encoding="utf-8").splitlines()}
base = {q["question_id"]: q for q in json.loads(
    (ROOT / "artifacts/benchmark_keys/regulus_acceptance_rev02@c009d5f9c649/baseline.json").read_text(encoding="utf-8"))["questions"]}
order = list(ev)

db = Database.from_env()
db.connect()
if str(db.status().get("default_transaction_read_only", "")).lower() not in ("on", "true", "1"):
    raise SystemExit("refusing: connection not read-only")


def write(name, cols, rows):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([f"# {LABEL}"])
        w.writerow(cols)
        for r in rows:
            w.writerow([" | ".join(map(str, r[c])) if isinstance(r.get(c), (list, tuple, set)) else r.get(c, "") for c in cols])


_heading = {}


def heading(sec):
    if sec not in _heading:
        rows = db.query("SELECT max(section_heading) h FROM cfr_records WHERE section_number=%(s)s AND removed_on IS NULL", {"s": sec})
        _heading[sec] = (rows[0]["h"] if rows else None) or ""
    return _heading[sec]


def sec_of(cite):
    m = re.search(r"(\d+\.\d+)", cite or "")
    return m.group(1) if m else None


DECL = re.compile(r"^(NO SUCH|FALSE PREMISE|TEMPORAL TRAP|MUST |OUT OF SCOPE|AMBIGUOUS|NOT COVERED|REPEALED|Guidance tier|Requirement source|ISO 14971)")


def granularity(g):
    if DECL.match(g.strip()):
        return "declaration"
    refs = parse_cfr_references(g)
    kinds = set()
    if re.search(r"FD&C Act|section \d{3}|MoCRA|(?<!C)FR \d", g):
        kinds.add("statute/FR")
    if re.search(r"\bSubpart\b", g, re.I):
        kinds.add("subpart")
    if re.search(r"\d\s*(through|–|-|to)\s*(\d|\()|et seq", g):
        kinds.add("range")
    for r in refs:
        if r.section is None:
            kinds.add("part")
        elif r.paragraph_path:
            kinds.add("paragraph")
        else:
            kinds.add("section")
    if not kinds:
        kinds.add("unparsed")
    return "+".join(sorted(kinds))


# =============================================================== FINDING 1
def cat(h):
    h = h.lower()
    if "record" in h: return "recordkeeping"
    if "definition" in h: return "definitions"
    if any(k in h for k in ("scope", "applicab", "purpose", "general", "who is subject", "exemption")): return "general/scope"
    return "substantive"


f1 = []
sat_by_cat, unsat_by_cat = Counter(), Counter()
for q in order:
    r, p = ev[q], prop[q]
    if not r["cited_provisions"]:
        continue
    cited = {c["section"] for c in r["cited_provisions"]}
    cited_parts = {s.split(".")[0] for s in cited}
    pointers, satisfied = set(), set()
    for c in r["cited_provisions"]:
        for t in c["outgoing_cross_references"]:
            s = sec_of(t)
            if not s or s == c["section"] or s.split(".")[0] not in cited_parts:
                continue
            (satisfied if s in cited else pointers).add(s)
    for s in satisfied:
        sat_by_cat[cat(heading(s))] += 1
    for s in pointers:
        unsat_by_cat[cat(heading(s))] += 1
    corr = p.get("proposed_corrected") or ""
    iso_only = corr.startswith("ISO key")
    corr_secs = set(re.findall(r"\d+\.\d+", corr)) if (p["proposed_decision"] == "CORRECTED" and not iso_only) else set()
    added = corr_secs - cited
    kind = ("" if p["proposed_decision"] != "CORRECTED" else "ISO-only" if iso_only else
            "additive (keeps every cited section)" if cited <= corr_secs else "substitutive (drops or replaces a cited section)")
    confirmed = sorted(added & pointers)
    if pointers or added or iso_only:
        f1.append({
            "question_id": q, "domain": r["domain"][:40], "draft_G": r["draft_citation_G"],
            "uncited_same_part_pointers": sorted(pointers),
            "pointer_categories": sorted({f"{s}:{cat(heading(s))}" for s in pointers}),
            "already_cited_pointer_targets": sorted(satisfied),
            "assisted_decision": p["proposed_decision"], "assisted_correction": corr,
            "correction_adds_pointed_section": confirmed,
            "correction_adds_unpointed_section": sorted(added - pointers),
            "correction_kind": kind,
            "class": ("CONFIRMED one-hop (J element found in pointed-to section)" if confirmed else
                      "correction adds section reached another way" if added else
                      "pointer present; key accepted as drafted" if p["proposed_decision"] == "ACCEPTED" else
                      "pointer present; row unresolved"),
        })


write("f1_one_hop_rows.csv", ["question_id", "domain", "draft_G", "class", "correction_kind", "uncited_same_part_pointers", "pointer_categories",
                              "already_cited_pointer_targets", "assisted_decision", "assisted_correction",
                              "correction_adds_pointed_section", "correction_adds_unpointed_section"], f1)
f1_classes = Counter(x["class"] for x in f1)
rows_with_pointer = sum(1 for x in f1 if x["uncited_same_part_pointers"])
rows_with_cites = sum(1 for q in order if ev[q]["cited_provisions"])

# =============================================================== FINDING 2
CL = re.compile(r"Clauses? ((?:\d+(?:\.\d+)*)(?:\s*(?:,|,?\s*and)\s*\d+(?:\.\d+)*)*)")


def clauses_in(text):
    out = []
    for m in CL.finditer(text or ""):
        out += re.findall(r"\d+(?:\.\d+)*", m.group(1))
    return list(dict.fromkeys(out))


def intro_text(c):
    whole = (c.get("whole_section") or c.get("provision") or {}).get("text", "")
    return "\n".join(l for l in whole.split("\n") if l.startswith("(section)"))


f2 = []
for q in order:
    r = ev[q]
    if r["draft_iso_H"] != "None":
        continue
    para = " ".join(c["provision"]["text"] for c in r["cited_provisions"])
    intro = " ".join(intro_text(c) for c in r["cited_provisions"])
    cw = {s: [x["clause"] for x in v] for s, v in (r["iso"] or {}).get("crosswalk_by_cited_section", {}).items()}
    f2.append({"question_id": q, "draft_G": r["draft_citation_G"], "question": r["question"],
               "clauses_named_in_cited_paragraph": clauses_in(para),
               "clauses_named_in_section_intro": clauses_in(intro),
               "mentions_ISO_13485_generically": bool(re.search(r"ISO 13485", para)),
               "crosswalk_section_level": cw,
               "platform_rule_would_name": sorted({c for v in cw.values() for c in v}),
               "assisted_proposal": prop[q]["proposed_decision"]})
write("f2_none_iso_rows.csv", ["question_id", "draft_G", "question", "clauses_named_in_cited_paragraph", "clauses_named_in_section_intro",
                               "mentions_ISO_13485_generically", "crosswalk_section_level", "platform_rule_would_name", "assisted_proposal"], f2)

# =============================================================== FINDING 3
f3 = []
by_para = defaultdict(list)
for q in order:
    r = ev[q]
    if r["iso"] is None:
        continue
    H = [c for c in base[q]["iso_clauses"]]
    named = []
    for c in r["cited_provisions"]:
        named += clauses_in(c["provision"]["text"])
        if c["paragraph"]:
            named += [f"{x} (intro)" for x in clauses_in(intro_text(c))]
        by_para[c["citation"]].append(q)
    plain = [n for n in named if not n.endswith("(intro)")]
    intro_only = sorted({n.replace(" (intro)", "") for n in named if n.endswith("(intro)")} - set(plain) - set(H))
    def covered(h):  # H clause is covered by a named clause (same or named parent/child)
        return any(h == n or h.startswith(n + ".") or n.startswith(h + ".") for n in plain)
    f3.append({"question_id": q, "draft_G": r["draft_citation_G"][:80], "draft_H": r["draft_iso_H"],
               "H_parsed": H, "clauses_named_in_cited_text": list(dict.fromkeys(named)),
               "named_but_not_in_H": sorted({n for n in plain if not any(n == h or n.startswith(h + ".") or h.startswith(n + ".") for h in H)}),
               "in_H_but_not_named": [h for h in H if plain and not covered(h)],
               "section_intro_clause_not_in_H": intro_only,
               "crosswalk": {s: [x["clause"] for x in v] for s, v in r["iso"]["crosswalk_by_cited_section"].items()},
               "assisted_tier": prop[q].get("iso_tier", "")})
write("f3_iso_vs_cfr_text.csv", ["question_id", "draft_G", "draft_H", "H_parsed", "clauses_named_in_cited_text",
                                 "named_but_not_in_H", "in_H_but_not_named", "section_intro_clause_not_in_H", "crosswalk", "assisted_tier"], f3)
same_para = []
for cite, qs in by_para.items():
    qs = list(dict.fromkeys(qs))
    if len(qs) > 1:
        hs = {q: ev[q]["draft_iso_H"] for q in qs}
        same_para.append({"citation": cite, "rows": qs, "H_by_row": [f"{q}={h}" for q, h in hs.items()],
                          "distinct_H": len(set(hs.values())),
                          "questions": [f"{q}: {ev[q]['question'][:90]}" for q in qs]})
write("f3_same_provision_iso.csv", ["citation", "rows", "distinct_H", "H_by_row", "questions"],
      sorted(same_para, key=lambda x: -x["distinct_H"]))

# =============================================================== FINDING 5
TS = [("date 2026", r"February 2, 2026|2026"), ("date 2024/2025", r"20(2[3-5])\b"), ("'as of'", r"\bas of\b"),
      ("current/status", r"\bcurrent(ly)?\b|\bstatus\b|\bproposed\b|\binterim\b"),
      ("MoCRA/cosmetics registration", r"MoCRA|\bPart 7[0-4]0\b|\b7[0-4]0\.\d"),
      ("legacy QSR wording", r"quality system(?! regulation\b.*QMSR)|\bQSR\b|DMR|DHR|DHF|device master|design history"),
      ("statute-only", None)]
f5 = []
for q in order:
    r = ev[q]
    blob = " || ".join([r["question"], r["draft_citation_G"], r["key_answer_elements_J"]])
    hits = [name for name, rx in TS if rx and re.search(rx, blob, re.I)]
    if granularity(r["draft_citation_G"]) in ("statute/FR", "unparsed") and not DECL.match(r["draft_citation_G"]):
        hits.append("statute-only")
    assisted = prop[q]
    flag_words = " ".join([assisted.get("key_elements_issue") or ""] + (assisted.get("needs_research_items") or []))
    if re.search(r"superseded|pre-QMSR|older|current 207|QMSR where|voluntary|Federal Register|stale|time-dependent", flag_words, re.I):
        hits.append("assisted review flagged drift/date")
    if hits:
        f5.append({"question_id": q, "question_type": r["question_type"], "signals": hits,
                   "draft_G": r["draft_citation_G"][:120], "J": r["key_answer_elements_J"][:160],
                   "assisted_decision": assisted["proposed_decision"]})
write("f5_time_sensitive_rows.csv", ["question_id", "question_type", "signals", "draft_G", "J", "assisted_decision"], f5)

# =============================================================== CROSS-QUESTION
# (a) same section, different expectations
by_sec = defaultdict(list)
for q in order:
    for c in ev[q]["cited_provisions"]:
        by_sec[c["section"]].append((q, c["citation"]))
clusters = []
for s, lst in by_sec.items():
    qs = list(dict.fromkeys(q for q, _ in lst))
    if len(qs) < 2:
        continue
    grans = {q: [c for qq, c in lst if qq == q] for q in qs}
    clusters.append({"section": s, "heading": heading(s), "rows": qs,
                     "citation_forms": [f"{q}:{'/'.join(v)}" for q, v in grans.items()],
                     "mixed_granularity": len({any('(' in c for c in v) for v in grans.values()}) > 1,
                     "distinct_H": len({ev[q]["draft_iso_H"] for q in qs}),
                     "question_types": sorted({ev[q]["question_type"] for q in qs}),
                     "J_by_row": [f"{q}: {ev[q]['key_answer_elements_J'][:110]}" for q in qs],
                     "assisted": [f"{q}={prop[q]['proposed_decision']}" for q in qs]})
write("xq_same_section_clusters.csv", ["section", "heading", "rows", "citation_forms", "mixed_granularity", "distinct_H",
                                       "question_types", "assisted", "J_by_row"], sorted(clusters, key=lambda x: -len(x["rows"])))

# (b) near-duplicate questions
dups = []
qs = [(q, re.sub(r"\W+", " ", ev[q]["question"].lower())) for q in order]
for i in range(len(qs)):
    for j in range(i + 1, len(qs)):
        a, b = qs[i], qs[j]
        ratio = difflib.SequenceMatcher(None, a[1], b[1]).ratio()
        shared = {c["section"] for c in ev[a[0]]["cited_provisions"]} & {c["section"] for c in ev[b[0]]["cited_provisions"]}
        if ratio >= 0.80 or (shared and ratio >= 0.60):
            dups.append({"a": a[0], "b": b[0], "similarity": round(ratio, 2), "shared_sections": sorted(shared),
                         "G_a": ev[a[0]]["draft_citation_G"][:70], "G_b": ev[b[0]]["draft_citation_G"][:70],
                         "H_a": ev[a[0]]["draft_iso_H"], "H_b": ev[b[0]]["draft_iso_H"],
                         "Q_a": ev[a[0]]["question"][:100], "Q_b": ev[b[0]]["question"][:100]})
write("xq_near_duplicates.csv", ["a", "b", "similarity", "shared_sections", "G_a", "G_b", "H_a", "H_b", "Q_a", "Q_b"],
      sorted(dups, key=lambda x: -x["similarity"]))

# (c) granularity distribution
gran = Counter()
gran_dom = defaultdict(Counter)
for q in order:
    g = granularity(ev[q]["draft_citation_G"])
    gran[g] += 1
    gran_dom[ev[q]["domain"][:45]][g] += 1
write("xq_citation_granularity.csv", ["domain", "distribution"],
      [{"domain": d, "distribution": [f"{k}={v}" for k, v in c.most_common()]} for d, c in gran_dom.items()])

# (d) negative-control / false-premise taxonomy vs platform failure rules
rules = db.query("SELECT rule_code, category, source_question_codes FROM acceptance_failure_rules WHERE is_active")
rule_of = defaultdict(list)
for r in rules:
    for c in r["source_question_codes"] or []:
        rule_of[c].append(r["rule_code"])
tax = []
for q in order:
    g = ev[q]["draft_citation_G"]
    lab = DECL.match(g.strip())
    if ev[q]["question_type"] in ("Negative Control", "Temporal/Version") or lab or rule_of.get(q):
        a =(prop[q].get("full_proposal") or {}).get("absence_assessment") or {}
        tax.append({"question_id": q, "question_type": ev[q]["question_type"],
                    "G_label": (lab.group(1).strip() if lab else g[:40]),
                    "platform_failure_rules": rule_of.get(q, []),
                    "what_is_actually_absent_or_reserved": a.get("result", ""),
                    "G": g[:110]})
write("xq_negative_control_taxonomy.csv", ["question_id", "question_type", "G_label", "platform_failure_rules",
                                           "what_is_actually_absent_or_reserved", "G"], tax)

# (e) temporal rows: date presence
temporal_rows = []
for q in order:
    blob = ev[q]["draft_citation_G"] + " " + ev[q]["key_answer_elements_J"]
    if re.search(r"\[?Reserved\]?|reserved", blob) or ev[q]["question_type"] == "Temporal/Version":
        temporal_rows.append({"question_id": q, "question_type": ev[q]["question_type"],
                              "states_date": bool(re.search(r"February 2, 2026", blob)),
                              "rules": rule_of.get(q, []), "G": ev[q]["draft_citation_G"][:120]})
write("xq_temporal_rows.csv", ["question_id", "question_type", "states_date", "rules", "G"], temporal_rows)

# (f) ISO naming style
style = []
for q in order:
    h = ev[q]["draft_iso_H"]
    if h in ("—", "None"):
        continue
    kind = ("parent+'and its subclauses'" if "subclause" in h.lower() else "range/entire" if re.search(r"through|entire", h) else
            "parent+enumerated children" if any(x.startswith(y + ".") for x in base[q]["iso_clauses"] for y in base[q]["iso_clauses"]) else
            "explicit list")
    style.append({"question_id": q, "H": h, "style": kind})
write("xq_iso_naming_style.csv", ["question_id", "H", "style"], style)

summary = {
    "_label": LABEL,
    "rows": len(order),
    "f1": {"rows_with_cfr_citations": rows_with_cites, "rows_whose_cited_text_points_to_uncited_same_part_section": rows_with_pointer,
           "classes": dict(f1_classes), "correction_kinds": dict(Counter(x["correction_kind"] for x in f1 if x["correction_kind"])),
           "pointer_targets_already_cited_by_category": dict(sat_by_cat),
           "pointer_targets_not_cited_by_category": dict(unsat_by_cat)},
    "f2_none_rows": [{k: v for k, v in x.items() if k != "question"} for x in f2],
    "f3": {"g7_rows": len(f3),
           "rows_H_omits_clause_named_in_cited_text": [x["question_id"] for x in f3 if x["named_but_not_in_H"]],
           "rows_H_names_clause_not_named_in_text_where_text_names_some": [x["question_id"] for x in f3 if x["in_H_but_not_named"]],
           "rows_where_only_the_section_intro_clause_is_absent_from_H": [x["question_id"] for x in f3 if x["section_intro_clause_not_in_H"] and not x["named_but_not_in_H"]],
           "same_provision_with_different_H": [x for x in same_para if x["distinct_H"] > 1]},
    "f5_rows": {x["question_id"]: x["signals"] for x in f5},
    "xq": {"same_section_clusters": len(clusters),
           "clusters_with_mixed_granularity": [c["section"] for c in clusters if c["mixed_granularity"]],
           "clusters_with_distinct_H": [c["section"] for c in clusters if c["distinct_H"] > 1],
           "near_duplicate_pairs": len(dups),
           "granularity": dict(gran),
           "temporal_rows_with_date": sum(1 for t in temporal_rows if t["states_date"]),
           "temporal_rows_without_date": sum(1 for t in temporal_rows if not t["states_date"]),
           "iso_naming_style": dict(Counter(s["style"] for s in style))},
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k not in ("f2_none_rows", "f5_rows")}, indent=1, ensure_ascii=False, default=str)[:6000])
