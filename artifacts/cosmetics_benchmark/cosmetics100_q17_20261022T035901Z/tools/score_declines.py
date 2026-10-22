"""Rubric verdicts for answers that are a plain decline ('The available regulatory sources do not provide enough
information ...', no substantive content). A decline on a question the verified key answers is Substantive 0 /
Completeness 0 -> FAIL. The explanation records what the evidence contained, so a reviewer can see whether the
required text was available. Writes scoring/batch_declines.json; prints the IDs that need individual scoring."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import evidence_check, load_run
run = Path(sys.argv[1]).resolve()
out, rest = {}, []
for it in load_run(run):
    q, r, resp = it["q"], it["r"], it["resp"]
    a = (r.get("answer") or "").strip()
    plain = (r.get("fallback_type") is None and a.startswith("The available regulatory sources do not provide enough information")
             and len(a) < 300)
    if not plain:
        rest.append(q["ID"]); continue
    ev = evidence_check(q, resp)
    cited = ", ".join(c.get("label", "")[:90] for c in resp.get("citations") or [] if c.get("cited_in_answer"))
    if ev["expected"]:
        miss = [s for s in ev["expected"] if s not in ev["in_evidence"]]
        if ev["in_evidence"] and not miss:
            evs = f"The key's section(s) {', '.join(ev['expected'])} WERE in the retrieved evidence, so the decline was made with the required text available."
            act = f"Declined with the required evidence present ({', '.join(ev['in_evidence'])}). Review the model's refusal behaviour on this question."
        elif ev["in_evidence"]:
            evs = f"Of the key's sections {', '.join(ev['expected'])}, only {', '.join(ev['in_evidence'])} was in the retrieved evidence."
            act = f"Declined with partial evidence ({', '.join(ev['in_evidence'])} retrieved; {', '.join(miss)} not)."
        else:
            evs = f"The key's section(s) {', '.join(ev['expected'])} were not in the retrieved evidence."
            act = f"Missing evidence: {', '.join(ev['expected'])} not retrieved, and the system declined."
        if ev["statute_key"]:
            evs += " The key also relies on the FD&C Act, which is not in the corpus."
    else:
        evs = "The key's source is the FD&C Act (statute), which is not in the Regulus corpus (eCFR and FDA guidance only)."
        act = "Corpus gap: the statute the key relies on is not in the corpus; the system declined."
    why = (f"Declined: 'The available regulatory sources do not provide enough information to answer this question'"
           + (f" (marker points to {cited})" if cited else "") + f". The verified key answers it ({q['Expected Citation — VERIFIED KEY']}), "
           f"so no supported answer was given where one is required. {evs}")
    out[q["ID"]] = {"ce": 0, "fab": 0, "sub": 0, "comp": 0, "scope": 1, "why": why, "action": act}
(run / "scoring" / "batch_declines.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(out), "declines scored;", len(rest), "need individual scoring:", " ".join(rest))
