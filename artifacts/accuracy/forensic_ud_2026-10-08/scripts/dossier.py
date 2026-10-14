import json, sys
rows = json.load(open("rows.json"))
KEEP = ["rev_key_sections","rev_key_section_state","rev_key_retrieved","rev_evidence_kind","rev_corpus_sufficient",
        "rev_substantively_correct","rev_mechanical_root_cause","rev_guidance_in_answer","rev_withheld",
        "rev_declined_before_model","rev_key_possibly_wrong","rev_key_better_candidate","rev_trap_row"]
for r in rows:
    if r["verdict"] != "unverifiable": continue
    L = []
    p = L.append
    p(f"########## {r['id']}  N={r['N']} M={r['M']} L={r['L']} O={r['O']} result={r['result']}  type={r['type']}  intent={r['intent']['kind'] if r['intent'] else None}")
    p(f"Q: {r['question']}")
    p(f"KEY: {r['key_citation']} | {r['key_elements']}")
    p("REV: " + "; ".join(f"{k[4:]}={r['rev'].get(k)}" for k in KEEP))
    p(f"NOTES: {r['notes']}")
    p(f"EVAL: {r['eval']}")
    p(f"PIPE: model_called={r['model_called']} fallback={r['fallback_type']} answerability={r['answerability']} validation={r['validation_final']}")
    p(f"ANSWER: {r['answer']}")
    p(f"EVIDENCE LABELS ({len(r['evidence_labels'])}, lost={r['docket_labels_without_text']}):")
    rebuilt = {s['citation'] for s in r['sources']}
    for l in r['evidence_labels']: p(f"   {'  ' if l in rebuilt else 'X '}{l[:150]}")
    p("SOURCES:")
    for s in r['sources']: p(f"   [{s['citation']}] ({s['heading']}) {s['text'][:260]!r}")
    p(f"REQS: {r['requirements']} satisfied={r['satisfied']}")
    p(f"INTENT: topic={r['intent'].get('topic')} elements={[e['label'] for e in r['intent'].get('elements',[])]} parts={r['intent'].get('parts')} sections={r['intent'].get('sections')}")
    p(f"VERDICT: {r['answer_verdict'].get('reason')} | missing={r['answer_verdict'].get('elements_missing')} unverified={r['answer_verdict'].get('elements_unverified')}")
    if r['abstention']: p(f"ABST: {json.dumps(r['abstention'])[:500]}")
    p(f"SENTENCES: {json.dumps(r['sentences'])[:1500] if r['sentences'] else r['sentences']}")
    for i, c in enumerate(r['claims'] or [], 1):
        rel = c.get('relevance') or {}
        p(f"  C{i}: final={c['final']} support={c['support']}/{c.get('support_basis')} rel={rel.get('verdict')} cit={c.get('citation')}")
        p(f"      text: {c['claim'][:300]}")
        p(f"      support_reason: {str(c.get('support_reason'))[:300]}")
        p(f"      rel_reason: {str(rel.get('reason'))[:250]} | found={rel.get('checks',{}).get('content_found_in_evidence')}")
        p(f"      evidence: {str(c.get('evidence'))[:200]} ops={c.get('operators')}")
    open(f"{r['id']}.txt","w").write("\n".join(L))
    print(r['id'], len("\n".join(L)))
