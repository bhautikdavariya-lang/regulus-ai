"""READ-ONLY check-level probes of the Phase 2L numeric reader (_p2l_compare), no verdict layer.
Evidence sentences are VERBATIM from numeric_cases.json texts; claims are CONSTRUCTED. Expect: None = no numeric finding."""
import json, sys
from regulus.accuracy import operators as OP
E211 = "shall be retained for at least 1 year after the expiration date of the batch"
E131 = "Its fat content is not more than 0.1 percent"  # trimmed real wording (131.160(b)(2) 'not more than 0.1 percent')
E1379 = "FDA may detain an article of food for a reasonable period that may not exceed 20 calendar days after the detention order is issued."
P = [
 ("P1 different ranges, both true", "Records shall be retained for no more than 3 years after the expiration date of the batch.", E211, None),
 ("P2 unit mismatch (months vs year)", "Records shall be retained for less than 12 months after the expiration date of the batch.", E211, None),
 ("P3 percent vs ppm, no conversion", "Its fat content is greater than 1000 ppm.", E131, None),
 ("P4 negation scope outside bound (claim)", "No record shall be retained for less than 1 year after the expiration date of the batch.", E211, None),
 ("P5 different event, same number", "FDA must hold a hearing within 20 calendar days after the appeal is filed.", E1379, None),
 ("P5b different event, opposite direction", "FDA must hold a hearing more than 20 calendar days after the appeal is filed.", E1379, None),
 ("P5c same subject, different trailing event", "FDA may detain an article of food for more than 20 calendar days after the appeal is filed.", E1379, None),
 ("P6 calendar vs business days", "FDA may detain an article of food for more than 20 business days after the detention order is issued.", E1379, None),
 ("P7 reversed, real reversal", "FDA may detain an article of food for a period exceeding 20 calendar days after the detention order is issued.", E1379, "conflict"),
 ("P8 equivalent ('maximum of')", "FDA may detain an article of food for a maximum of 20 calendar days after the detention order is issued.", E1379, None),
 ("P9 written-out number", "Records shall be retained for less than one year after the expiration date of the batch.", E211, "conflict"),
]
out = []
for name, cl, ev, exp in P:
    r = OP._p2l_compare(cl, ev); got = r[0] if r else None
    ok = (got == exp) if exp != "?" else True
    out.append({"probe": name, "claim": cl, "evidence": ev, "expect": exp, "got": got, "detail": None if not r else str(r[1]), "ok": ok,
                "claim_bounds": [list(map(str, b[:3])) for b in OP._p2l_bounds(cl)], "evidence_bounds": [list(map(str, b[:3])) for b in OP._p2l_bounds(ev)]})
    print(f"{'ok ' if ok else 'XX '} {name:42} expect={exp} got={got} | cb={out[-1]['claim_bounds']} eb={out[-1]['evidence_bounds']}")
json.dump(out, open(sys.argv[1] + f"/numeric_probes_{sys.argv[2]}.json", "w"), indent=1)
