"""READ-ONLY: how many current eCFR paragraphs carry more than one mandatory sentence (the rows whose completeness
unit the obligation-level design would split), using the evaluator's own sentence splitter and strength operator."""
import collections, json, sys
from regulus.accuracy import operators as OP
from regulus.accuracy.alignment import passages
from regulus.retrieval import Database
from types import SimpleNamespace as NS
db = Database.from_env(); db.connect()
rows = db.query("SELECT section_number, paragraph_path, body_text FROM cfr_records WHERE removed_on IS NULL AND coalesce(body_text,'') <> ''")
dist = collections.Counter(); examples = collections.defaultdict(list); total_mand = 0
for r in rows:
    ps = passages([NS(index=1, citation="x", text=r["body_text"], heading=None, tier="exact", corpus="ecfr")])
    k = sum(1 for p in ps if OP.strength(p.text) == OP.MANDATORY)
    if k: total_mand += 1
    b = k if k < 6 else 6
    dist[b] += 1
    if k >= 2 and len(examples[b]) < 3: examples[b].append(f"{r['section_number']}{r['paragraph_path']}")
out = {"rows": len(rows), "rows_with_a_mandatory_sentence": total_mand,
       "mandatory_sentences_per_row (6 = 6+)": dict(sorted(dist.items())), "examples": dict(examples)}
print(json.dumps(out, indent=1)); open(sys.argv[1], "w").write(json.dumps(out, indent=1))
