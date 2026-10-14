"""READ-ONLY Phase 2M: reproduce and trace the seven open cases (T3c, DX4, DX2, N9, N10, N12, N15) with whatever
regulus.accuracy is loaded (run via use_variant_ro.py). Texts are read from the Phase 2L inputs, never rewritten."""
import json, re, sys
sys.path.insert(0, ".")
from regulus.accuracy import operators as OP
from tests.test_accuracy_claim_extraction import judge
W, NAME = sys.argv[1] + "/work/", sys.argv[2]
real = {r["id"]: r for r in json.load(open(W + "controls_real.json"))}
dx = {r["id"]: r for r in json.load(open(W + "diagnostics.json"))}
nc = {r["id"]: r for r in json.load(open(W + "numeric_cases.json"))["cases"]}
CASES = []
r = real["T3c"]; CASES.append(dict(id="T3c", source="controls_real.json", citation=r["evidence_citation"], evidence=r["evidence"], claim=r["claim"],
                                  expect=r["expect"], claim_provenance=r["claim_provenance"], evidence_provenance="REAL verbatim (" + r["evidence_snapshot"] + ")", sha=r["evidence_sha256"]))
for i in ("DX4", "DX2"):
    r = dx[i]; CASES.append(dict(id=i, source="diagnostics.json", citation=r["citation"], evidence=r["evidence"], claim=r["claim"], expect=r["expect"],
                                 claim_provenance=r.get("claim_provenance", "CONSTRUCTED"), evidence_provenance="REAL verbatim (" + r["snapshot_date"] + ")", sha=r["content_sha256"]))
for i in ("N9", "N10", "N12", "N15"):
    r = nc[i]; CASES.append(dict(id=i, source="numeric_cases.json", citation=r["citation"], evidence=r["evidence"], claim=r["claim"], expect=r["expect"],
                                 claim_provenance=r.get("claim_provenance", "CONSTRUCTED"), evidence_provenance=r.get("evidence_provenance"), sha=r["content_sha256"]))
SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")
out = []
for c in CASES:
    cmp = OP.compare(c["claim"], c["evidence"])
    a = judge(f"What does {c['citation']} require?", c["claim"] + " [1]", [(c["citation"], c["evidence"])])
    cl = a.checked["claims"][0] if a.checked["claims"] else {}
    units = [s for s in SENT.split(c["evidence"]) if s.strip()]
    rec = {**c, "variant": NAME,
           "claim_ops": cmp.claim_operators, "evidence_ops": cmp.evidence_operators,
           "conflicts": [x["operator"] + ": " + x["detail"] for x in cmp.conflicts], "agreed": list(cmp.agreed),
           "omissions": [o["detail"] for o in cmp.omissions], "support_blocked": cmp.support_blocked,
           "evidence_main_clause": OP.main_clause(c["evidence"]), "claim_main_clause": OP.main_clause(c["claim"]),
           "negators_in_evidence_main_clause": [m.group(0) for m in OP._NEGATE_RE.finditer(OP.main_clause(c["evidence"]))],
           "strength_hits_evidence": [(n, m.group(0)) for n, p in OP._STRENGTH_PATTERNS for m in p.finditer(OP.main_clause(c["evidence"]))][:6],
           "units": [{"text": u, "strength": OP.strength(u), "polarity": OP.polarity(u)} for u in units],
           "basis": cl.get("support_basis"), "final": cl.get("final"), "claim_reason": cl.get("reason") or cl.get("verdict_reason"),
           "gate": {k: (cl.get("content_gate") or {}).get(k) for k in ("content_gate_verdict", "content_support_reason", "support_block_reason", "operators_agreed", "term_overlap", "core_overlap", "verbatim_coverage")} if cl.get("content_gate") else None,
           "claim_keys": sorted(cl.keys())}
    out.append(rec)
    print(f"== {c['id']} [{NAME}] expect={c['expect']} -> basis={rec['basis']} final={rec['final']}")
    print(f"   conflicts={rec['conflicts']} agreed={rec['agreed']} blocked={rec['support_blocked']}")
    print(f"   claim  str={cmp.claim_operators['strength']} pol={cmp.claim_operators['polarity']} q={cmp.claim_operators.get('quantities')}")
    print(f"   evid   str={cmp.evidence_operators['strength']} pol={cmp.evidence_operators['polarity']} q={cmp.evidence_operators.get('quantities')} negators={rec['negators_in_evidence_main_clause']}")
json.dump(out, open(W + f"trace_{NAME}.json", "w"), indent=1, ensure_ascii=False)
