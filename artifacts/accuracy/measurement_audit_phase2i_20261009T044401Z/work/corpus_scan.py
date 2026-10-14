"""READ-ONLY corpus scan (server-enforced read-only connection): every sentence in the local eCFR snapshot
with a negation directly after 'that/which/who'. Records citation, sentence, the word before the pronoun,
and how production polarity reads the sentence."""
import json, re, sys
from collections import Counter
from regulus.retrieval import Database
from regulus.accuracy import operators as OP
from regulus.evaluation.grounding_eval import split_sentences
OUT = sys.argv[1]
REL = re.compile(r"\b(that|which|who)\s+((?:do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+not|cannot)\b", re.I)
db = Database.from_env(); db.connect()
rows = db.query("SELECT part_number, section_number, paragraph_path, section_heading, body_text, snapshot_date FROM cfr_records "
                "WHERE removed_on IS NULL AND NOT is_reserved AND body_text ~* %s", (r"\m(that|which|who)\s+((do|does|did|is|are|was|were|will|can|could|may|must|shall|has|have|had|would|should)\s+not|cannot)\M",))
db.close()
hits = []
for r in rows:
    for s in split_sentences(r["body_text"] or ""):
        for m in REL.finditer(s):
            words = re.findall(r"[A-Za-z]+", s[: m.start()])
            hits.append({"citation": f"21 CFR {r['section_number']}{r['paragraph_path'] or ''}", "heading": r["section_heading"],
                         "snapshot_date": str(r["snapshot_date"]), "sentence": s.strip(), "pronoun": m.group(1).lower(),
                         "negation": m.group(2).lower(), "word_before": words[-1].lower() if words else "",
                         "strength": OP.strength(s), "polarity": OP.polarity(s)})
json.dump(hits, open(OUT, "w"), indent=1, ensure_ascii=False)
print("records matched:", len(rows), "| sentences with a relative-pronoun negation:", len({(h["citation"], h["sentence"]) for h in hits}), "| matches:", len(hits))
print("by pronoun:", Counter(h["pronoun"] for h in hits))
print("sentences with a modal (strength set):", sum(1 for h in hits if h["strength"]), "| production polarity:", Counter(h["polarity"] for h in hits))
print("top words before the pronoun:", Counter(h["word_before"] for h in hits).most_common(45))
