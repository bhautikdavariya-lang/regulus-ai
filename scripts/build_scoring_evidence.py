import json, re, sys, textwrap
sys.path.insert(0, "src")
from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
from regulus.retrieval import Database
from regulus.retrieval.references import parse_cfr_references

run = sys.argv[1]; outdir = sys.argv[2]
bench = list(load_acceptance_benchmark())
rows = {json.loads(l)["question_id"]: json.loads(l) for l in open(f"{run}/answers.jsonl")}
db = Database.from_env(); db.connect()

def sec_text(section, limit=1100):
    r = db.query("SELECT section_heading, is_reserved FROM cfr_records WHERE section_number=%s LIMIT 1", (section,))
    if not r:
        rng = db.query("SELECT number FROM cfr_sections WHERE number LIKE %s AND number LIKE '%%-%%'", (section.split('.')[0] + '.%',))
        return f"NOT PRESENT in current snapshot (reserved spans in this part: {[x['number'] for x in rng]})"
    head = f"[{section} {r[0]['section_heading']}]"
    body = db.query("SELECT paragraph_path, body_text FROM cfr_records WHERE section_number=%s ORDER BY path_ordinal, ordinal", (section,))
    parts = [f"{b['paragraph_path'] or ''} {(b['body_text'] or '').strip()}" for b in body]
    t = head + " " + " ".join(parts)
    t = re.sub(r"\s+", " ", t)
    return t[:limit] + (" …[cut]" if len(t) > limit else "")

chunks, cur = [], []
for q in bench:
    r = rows.get(q.question_id, {})
    ans = r.get("answer") or "(no answer recorded)"
    raw = r.get("raw_model_output") or ""
    keyrefs = [x.section for x in parse_cfr_references(q.expected_citation_draft) if x.title == "21" and x.section]
    law = "\n".join("  LAW " + sec_text(s) for s in dict.fromkeys(keyrefs)) or "  LAW (draft key names no single section)"
    marks = {int(m) for m in re.findall(r"\[(\d{1,3})\]", ans)}
    by_i = {c["index"]: c["label"] for c in r.get("citations") or []}
    cites = ", ".join(f"[{i}]={by_i.get(i, 'INVALID/no such source')}" for i in sorted(marks)) or "(no [n] markers in answer)"
    block = (f"### {q.question_id} | type={q.question_type} | domain={q.domain} | ISO_key={q.iso_clause_draft!r} "
             f"g7={q.in_g7_scope} neg_control={q.is_negative_control} temporal={q.is_temporal} scope_bdry={q.is_scope_boundary}\n"
             f"  Q: {q.question}\n"
             f"  DRAFT_KEY_CITATION: {q.expected_citation_draft}\n"
             f"  KEY_ELEMENTS: {q.key_answer_elements}\n"
             f"{law}\n"
             f"  EXEC: {r.get('execution_status')} err={r.get('error')}\n"
             f"  MODEL_ANSWER: {re.sub(chr(10),' ', ans)[:1500]}\n"
             + (f"  RAW_BEFORE_REPAIR: {re.sub(chr(10),' ', raw)[:600]}\n" if r.get("repair") else "")
             + f"  CITES_MARKER_TO_SOURCE: {cites}\n"
             + f"  PIPE: answerability={r.get('answerability')} final_validation={r.get('validation_final')} repair={r.get('repair')}\n")
    cur.append(block)
    if len(cur) == 25:
        chunks.append(cur); cur = []
if cur: chunks.append(cur)
db.close()
for i, c in enumerate(chunks, 1):
    open(f"{outdir}/chunk{i:02d}.txt", "w").write("\n".join(c))
print("chunks:", len(chunks), "questions:", sum(len(c) for c in chunks))
