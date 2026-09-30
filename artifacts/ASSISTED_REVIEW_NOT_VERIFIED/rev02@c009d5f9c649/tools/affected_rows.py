"""ASSISTED REVIEW — NOT VERIFIED — consolidated affected-row list (read-only).

One line per (row, issue). Classification:
  A clearly acceptable · B clearly requires key correction · C requires SME policy decision
  D requires external authoritative source · E requires benchmark-rubric clarification
Nothing here changes a key. "B" means the eCFR text in evidence shows the key is wrong;
the SME still decides and records it through the review tool.
"""

import csv
import json
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
INV = PKG / "integrity_investigation"


def rd(name):
    rows = list(csv.reader((INV / name).open(encoding="utf-8-sig")))
    return [dict(zip(rows[1], r)) for r in rows[2:]]


prop = {json.loads(l)["question_id"]: json.loads(l) for l in (PKG / "02_proposals_full.jsonl").read_text(encoding="utf-8").splitlines()}
out = []


def add(q, issue, cls, note):
    out.append({"question_id": q, "issue": issue, "classification": cls, "note": note})


# ---- Finding 1
RECORDKEEPING_ADDS = {"D-007": "211.182", "S-027": "111.570", "H-002": "1.360", "T-003": "1114.45", "Y-006": "114.100",
                      "F-019": "117.320 (records availability)", "P-010": "812.140"}
for r in rd("f1_one_hop_rows.csv"):
    q, kind = r["question_id"], r["correction_kind"]
    if kind.startswith("substitutive"):
        add(q, "F1 key cites the wrong/neighbouring section", "B", f"proposed: {r['assisted_correction']}")
    elif kind.startswith("additive"):
        if q in RECORDKEEPING_ADDS:
            add(q, "F1 one-hop: cross-referenced recordkeeping section not in key", "B/E",
                f"rubric O names 'cross-referenced recordkeeping'; add {RECORDKEEPING_ADDS[q]}")
        else:
            add(q, "F1 one-hop: pointed-to section holds a J element", "C",
                f"policy P1 decides; proposed: {r['assisted_correction']}")
    elif r["class"].startswith("pointer present; key accepted"):
        add(q, "F1 pointer to uncited section, key accepted as drafted", "A",
            "acceptable under any P1 option unless the pointer is recordkeeping: " + r["pointer_categories"][:160])

add("L-015", "F1 part-level key names the wrong subpart ('Subpart B of Part 101'; 102.5(d) means Part 102 Subpart B)", "B",
    "proposed: 21 CFR 101.3(b); 21 CFR 102.5; 21 CFR Part 102, Subpart B")

# ---- Finding 2
for q in ("M-002", "M-003", "M-004", "M-005", "M-006", "M-007"):
    add(q, "F2 'None' ISO key; section-level crosswalk names 1/4.1", "C/E",
        "paragraph names no clause (None defensible under paragraph rule); platform crosswalk rule would name 1/4.1 -> Q=0 and M=1 (G2)")
add("M-019", "F2 'None' ISO key", "A", "paragraph names no clause; crosswalk silent; consistent")
add("M-024", "F2 'None' ISO key while section intro names 4.2.5", "C/E",
    "strongest case: 820.35 intro frames (d) as 'in addition to Clause 4.2.5'; naming 4.2.5 would be scored fabricated")

# ---- Finding 3
add("X-003", "F3 H omits clauses the cited 4.4(b)(1) enumerates (4.1, 5, 6.1, 8.2.2, 8.4)", "B/E",
    "question asks which provisions must be satisfied; naming style (8.5 vs 8.5.2/8.5.3) needs rubric rule")
add("M-029", "F3 H omits 7.2.3, 7.3, 8.3.3 named in cited 820.10(b)(4)/(c)", "B/C", "depends on P3 (list all clauses the cited text names?)")
add("M-042", "F3 H omits 7.5.1 for 820.35(c); M-023 includes it", "C", "actual inconsistency between two rows citing the same paragraph")
add("M-023", "F3 same paragraph as M-042, different H", "C", "pair with M-042")
add("M-006", "F3 820.1(c) keyed None here, '1; 4.1' in M-041", "C", "actual inconsistency on the same paragraph")
add("M-041", "F3 820.1(c) keyed '1; 4.1' here, None in M-006", "C", "pair with M-006")
add("M-018", "F3 820.10(d) keyed 7.5.9.2 here, parent 7.5.9 in M-029", "E", "clause-granularity naming")
add("M-028", "F3 H adds 4.2.3 not named in 820.45(c)", "C", "term 'medical device file' only")
for q in ("M-021", "M-022", "M-023", "M-027", "M-033", "PB-009"):
    add(q, "F3 H uses paragraph clause, omits section-intro clause", "A", "consistent with the key's paragraph-level rule; conflicts only with the section-level crosswalk")
for r in json.loads((INV / "platform_crosswalk_vs_H.json").read_text(encoding="utf-8")):
    if r["outcome"] != "match":
        add(r["question_id"], "F3/P4 platform crosswalk-only ISO rule disagrees with H", "C/E", r["outcome"])

# ---- Finding 4 (column J)
for q, p in prop.items():
    if p.get("key_elements_issue"):
        add(q, "F4 column J not fully supported by regulation text", "C", p["key_elements_issue"][:200])

# ---- Finding 5
for q in ("M-030", "M-031", "PB-008", "NC-003", "NC-005", "NC-011", "NC-016"):
    add(q, "F5 states 'February 2, 2026' (effective/compliance date) — not in the eCFR snapshot", "D",
        "Federal Register 89 FR 7523 (and check 89 FR 82945, Oct 15 2024, carried in the snapshot source note)")
for q in ("M-032", "M-033", "M-034", "M-035", "M-036", "M-037", "M-038", "M-039", "M-040"):
    add(q, "F5/XQ reserved-section row without the date, while rubric criterion 4 and the §6 worked example (M-033) use it", "E",
        "decide whether the date is required in answers")
add("C-001", "F5 MoCRA registration; CFR Part 710 still describes voluntary registration", "D", "FD&C Act §607 (as added by MoCRA) + FDA's current registration/listing materials")
add("C-005", "F5 MoCRA adverse-event reporting (statute only)", "D", "FD&C Act §605")
add("C-002", "F5 cosmetic labeling rows may predate MoCRA label additions", "D", "FD&C Act §§604-609 vs 21 CFR 701")
add("M-006", "F5 J (refusal of inspection) not in current 820.1(c)", "D", "live eCFR 820.1(c) + FD&C Act 801(a)")
add("G-009", "F5 J wording ('preparation, propagation, compounding, or processing') differs from current 207.17(a)", "B", "snapshot text shows current wording")
add("X-002", "F5 J says 'device quality system requirements'; current text says QMSR", "C", "wording only")
add("X-003", "F5 J contains a reviewer instruction about the Feb 2 2026 restructuring", "B", "J is not an answer element; snapshot already answers it")
add("T-011", "F5 'current status of rulemaking' — time-dependent key", "C/D", "policy on time-dependent questions + current Unified Agenda/FR")
for q in ("NC-015", "NC-022"):
    add(q, "F5 guidance-absence claim is time-sensitive", "D", "FDA guidance database on the date the key is locked")
add("PB-003", "F5 vehicle of the HPHC list (guidance vs FR notice)", "D", "FDA / Federal Register")

# ---- Cross-question
for q in ("M-031", "NC-011", "NC-016"):
    add(q, "XQ 820.30 labelled three ways (TEMPORAL TRAP / FALSE PREMISE / REPEALED PROVISION)", "E",
        "ISO differences follow the question subject (A); label differences do not")
for q in ("NC-005", "NC-011", "NC-016"):
    add(q, "XQ reserved section scored under G3 'does not exist' criterion and under TV 'is reserved' rule", "E", "criteria conflict")
add("NC-014", "XQ nonexistent paragraph labelled FALSE PREMISE (sections use NO SUCH SECTION)", "E", "taxonomy")
add("M-037", "XQ ISO style: parent + enumerated subclauses", "E", "vs '7.3 and its subclauses' (M-017, M-031)")
add("PB-005", "XQ ISO subset 7.4; 7.4.1 for supplier qualification vs M-037 full 7.4 family", "C", "question scope may justify")
for q in ("F-022", "L-015", "P-007", "T-005", "T-006", "T-007", "T-008", "A-004", "Z-004", "M-042"):
    add(q, "XQ part/subpart-level citation", "E", "G1 scores to the section/paragraph; how to score against a part-level key")
for q in ("T-011", "T-012", "C-001", "C-005"):
    add(q, "XQ statute-only key", "D", "FD&C Act not held in the project")

with (INV / "affected_rows.csv").open("w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, ["question_id", "issue", "classification", "note"])
    fh.write("# ASSISTED REVIEW — NOT VERIFIED — affected rows; no key has been changed\n")
    w.writeheader()
    w.writerows(out)
from collections import Counter
print(len(out), "row-issue lines;", len({o['question_id'] for o in out}), "distinct rows")
print(Counter(o["classification"] for o in out))
