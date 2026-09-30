"""Audit test battery. Read-only: posts questions to the running local UI
server (scripts/serve_ui.py) and records the complete response for each.
Nothing in the project is modified; results go to audit/results/.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path("audit/results")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000/api/ask"

# (id, category, question, gate)
TESTS = [
    # A: individual provisions
    ("A1", "A", "What does 21 CFR § 820.10(b)(1) require?", False),
    ("A2", "A", "What does 21 CFR § 820.10(b)(2) require?", False),
    ("A3", "A", "What does 21 CFR § 820.10(b)(3) require?", False),
    ("A4", "A", "What does 21 CFR § 820.10(b)(4) require?", False),
    # B: multi-provision
    ("B1", "B", "What are the requirements of 21 CFR § 820.10(b)(1) and § 820.10(b)(2)?", False),
    ("B2", "B", "What are the requirements of 21 CFR § 820.10(b)(1), (b)(2), and (b)(3)?", False),
    ("B3", "B", "List all of the specific requirements in 21 CFR § 820.10(b)(1) through (b)(4).", False),
    ("B4", "B", "Compare the requirements of § 820.10(b)(2) and § 820.10(b)(4).", False),
    ("B5", "B", "Explain the requirements of § 820.10(b)(1) through § 820.10(b)(4) in plain English.", False),
    # C: range phrasings
    ("C1", "C", "§820.10(b)(1)-(b)(4)", False),
    ("C2", "C", "§820.10(b)(1) through (b)(4)", False),
    ("C3", "C", "§820.10(b)(1) to (b)(4)", False),
    ("C4", "C", "820.10(b)(1), 820.10(b)(2), 820.10(b)(3), 820.10(b)(4)", False),
    ("C5", "C", "820.10(b)(1)-(4)", False),
    ("C6", "C", "subsections (b)(1) through (b)(4) of 820.10", False),
    ("C7", "C", "all requirements under 820.10(b)", False),
    # Special Test A (parent paragraph)
    ("S1", "S", "What does 21 CFR § 820.10(b) require manufacturers to comply with?", False),
    # D: general regulatory, no citation
    ("D1", "D", "What are the traceability requirements for manufacturers?", False),
    ("D2", "D", "When must a manufacturer notify FDA about a complaint?", False),
    ("D3", "D", "What requirements apply to advisory notices?", False),
    ("D4", "D", "What is required for unique device identification?", False),
    ("D5", "D", "What records-related requirements apply to a medical device manufacturer?", False),
    # E: unsupported / general knowledge, gate OFF then ON
    ("E1-off", "E", "What is the capital of France?", False),
    ("E1-on", "E", "What is the capital of France?", True),
    ("E2-off", "E", "Who wrote Hamlet?", False),
    ("E2-on", "E", "Who wrote Hamlet?", True),
    ("E3-off", "E", "What is the boiling point of water in Celsius?", False),
    ("E3-on", "E", "What is the boiling point of water in Celsius?", True),
    ("E4-off", "E", "What does 21 CFR 820.10(b)(2) require?", False),  # supported control
    ("E4-on", "E", "What does 21 CFR 820.10(b)(2) require?", True),
    # F: partially supported
    ("F1", "F", "What does 21 CFR 820.10(b)(3) require, and what is the population of Paris?", False),
    ("F2", "F", "What do 21 CFR 820.10(b)(2) and 21 CFR 820.999 require?", False),
    ("F3", "F", "Explain the UDI requirement in 21 CFR 820.10(b)(1) and the history of the Eiffel Tower.", False),
    # I: hallucination / constraint
    ("I1-off", "I", "What are the specific requirements of 21 CFR 314.999?", False),
    ("I1-on", "I", "What are the specific requirements of 21 CFR 314.999?", True),
    ("I2-off", "I", "What does 21 CFR Part 1400 say about artificial intelligence in drug labeling?", False),
    ("I2-on", "I", "What does 21 CFR Part 1400 say about artificial intelligence in drug labeling?", True),
    ("I3", "I", "What penalty amount does 21 CFR 820.10(b)(3) specify for late complaint notification?", False),
    ("I4", "I", "Which FDA form number must be used under 21 CFR 820.10(b)(4)?", False),
    # J: paraphrase stability
    ("J1", "J", "What does §820.10(b)(3) require?", False),
    ("J2", "J", "Explain §820.10(b)(3).", False),
    ("J3", "J", "What must a manufacturer do under §820.10(b)(3)?", False),
    ("J4", "J", "What obligation does §820.10(b)(3) impose?", False),
    ("J5", "J", "Under §820.10(b)(3), when must FDA be notified?", False),
    # K: follow-ups (the pipeline is single-turn; run as standalone to document that)
    ("K1", "K", "What does 21 CFR §820.10(b)(2) require?", False),
    ("K2", "K", "Why is that requirement important?", False),
    ("K3", "K", "Which part applies to that?", False),
]

only = set(sys.argv[1:])
log = OUT / "battery.jsonl"
done = {json.loads(l)["id"] for l in log.read_text(encoding="utf-8").splitlines() if l.strip()} if log.is_file() else set()
for tid, cat, q, gate in TESTS:
    if only and tid not in only:
        continue
    if tid in done:
        continue
    t0 = time.time()
    req = urllib.request.Request(URL, data=json.dumps({"question": q, "adapter": "", "grounding": gate, "top_k": 8, "max_new_tokens": 128}).encode(), headers={"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=900))
        r["_id"], r["_category"], r["_gate"], r["_error"] = tid, cat, gate, None
    except Exception as exc:
        r = {"_id": tid, "_category": cat, "_gate": gate, "question": q, "_error": str(exc)[:300]}
    r["id"] = tid
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    ans = (r.get("answer") or r.get("_error") or "")[:90].replace("\n", " ")
    g = (r.get("grounding") or {}).get("action")
    print(f"[{tid:<7}] {time.time()-t0:5.1f}s gate={'on ' if gate else 'off'} action={g or '-':<7} :: {ans}", flush=True)
print("BATTERY COMPLETE", flush=True)
