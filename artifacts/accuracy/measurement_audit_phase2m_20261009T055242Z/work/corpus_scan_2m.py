"""READ-ONLY corpus scan (server-enforced read-only connection) for Phase 2M exposure and diagnostic sourcing.
Per mechanism: how many eCFR sentences carry it and how PRODUCTION operators read them. Nothing is written outside OUT."""
import json, re, sys, hashlib
from collections import Counter
from regulus.retrieval import Database
from regulus.accuracy import operators as OP
from regulus.evaluation.grounding_eval import split_sentences
OUT = sys.argv[1]
db = Database.from_env(); db.connect()
ro = db.query("SELECT current_setting('transaction_read_only') AS ro")[0]["ro"]
rows = db.query("SELECT section_number, paragraph_path, body_text, snapshot_date FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved "
                "AND body_text ~* %s", (r"(may\s+not|exempt|calendar\s+days|business\s+days|working\s+days|;\s+[a-z][^;]*\m(shall|must)\s+not)",))
db.close()
REL_MODAL = re.compile(r"\b(?:that|which|who)\s+(?:may|shall|must)\s+not\b", re.I)
MAYNOT_EXCEED = re.compile(r"\bmay\s+not\s+exceed\b", re.I)
EXEMPT = re.compile(r"\bexempt(?:s|ed|ion|ions)?\b", re.I)
DAYQ = re.compile(r"\b\d+\s+(calendar|business|working)\s+days?\b", re.I)
out = {"read_only": ro, "records": len(rows), "maynot_exceed": [], "rel_modal_main_may": [], "exempt_affirm_modal": [], "dayq": Counter(),
       "semicolon_mixed": []}
for r in rows:
    cit = f"21 CFR {r['section_number']}{r['paragraph_path'] or ''}"
    for s in split_sentences(r["body_text"] or ""):
        s = s.strip()
        if MAYNOT_EXCEED.search(s):
            out["maynot_exceed"].append({"citation": cit, "sentence": s, "strength": OP.strength(s), "polarity": OP.polarity(s)})
        m = REL_MODAL.search(s)
        if m and re.search(r"\bmay\b(?!\s+not)", s[: m.start()], re.I):
            out["rel_modal_main_may"].append({"citation": cit, "sentence": s, "strength": OP.strength(s)})
        mc = OP.main_clause(s)
        if EXEMPT.search(mc) and not re.search(r"\b(?:shall|must|may|can|will|does|do|is|are|were|was)\s+not\b|\bcannot\b|\bneed\s+not\b|\bnot\s+subject\b|\bnot\s+applicable\b|\bprohibit", mc, re.I) and OP.strength(s):
            out["exempt_affirm_modal"].append({"citation": cit, "sentence": s, "strength": OP.strength(s), "polarity": OP.polarity(s),
                                               "exempt_word_before": (re.findall(r"[A-Za-z]+", mc[: EXEMPT.search(mc).start()]) or [""])[-1].lower()})
        for q in DAYQ.finditer(s): out["dayq"][q.group(1).lower()] += 1
        parts = [p for p in re.split(r";\s+", s) if p.strip()]
        if len(parts) > 1:
            pols = [OP.polarity(p) for p in parts]
            if "affirm" in pols and "negate" in pols:
                out["semicolon_mixed"].append({"citation": cit, "sentence": s, "clause_polarity": pols, "sentence_polarity": OP.polarity(s)})
summ = {"read_only": ro, "records_matched": len(rows),
        "may_not_exceed_sentences": len(out["maynot_exceed"]), "may_not_exceed_read_mandatory": sum(1 for x in out["maynot_exceed"] if x["strength"] == "mandatory"),
        "relative_modal_negation_with_main_may": len(out["rel_modal_main_may"]),
        "exempt_word_in_main_clause_of_otherwise_affirmative_modal_sentence": len(out["exempt_affirm_modal"]),
        "exempt_affirm_read_negate": sum(1 for x in out["exempt_affirm_modal"] if x["polarity"] == "negate"),
        "exempt_word_before": Counter(x["exempt_word_before"] for x in out["exempt_affirm_modal"]).most_common(15),
        "qualified_day_mentions": dict(out["dayq"]),
        "semicolon_sentences_mixed_clause_polarity": len(out["semicolon_mixed"]),
        "semicolon_mixed_read_negate_whole": sum(1 for x in out["semicolon_mixed"] if x["sentence_polarity"] == "negate")}
out["summary"] = summ; out["dayq"] = dict(out["dayq"])
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
print(json.dumps(summ, indent=1))
