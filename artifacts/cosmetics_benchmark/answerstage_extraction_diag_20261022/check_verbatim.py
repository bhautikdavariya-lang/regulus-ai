"""Parse PART/EVIDENCE lines and check each quoted sentence verbatim against its cited source."""
import json, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
RUN = HERE.parents[0] / "cosmetics100_q17_20261022T035901Z"
qs = {q["ID"]: q for q in json.loads((RUN / "selection.json").read_text())["questions"]}
norm = lambda s: re.sub(r"\s+", " ", s.replace("“", '"').replace("”", '"').replace("’", "'")).strip().lower()
rows = []
for l in (HERE / "outputs.jsonl").read_text().splitlines():
    o = json.loads(l)
    resp = json.loads((RUN / "responses" / f"{o['id']}.json").read_text())
    src = {s["index"]: (s["citation"], s["text"]) for s in resp["sources"]}
    lines = []
    for m in re.finditer(r"EVIDENCE:\s*(.*)", o["output"]):
        ev = m.group(1).strip()
        if "NOT IN SOURCES" in ev.upper():
            lines.append({"ev": "NOT IN SOURCES"}); continue
        q = re.search(r'["“](.+?)["”]\s*\[(\d+)\]', ev) or re.search(r'["“](.+)["”]', ev)
        idx = int(q.group(2)) if q and q.lastindex == 2 else (int(re.search(r"\[(\d+)\]", ev).group(1)) if re.search(r"\[(\d+)\]", ev) else None)
        quote = q.group(1) if q else ev
        cit, text = src.get(idx, ("?", ""))
        verb = norm(quote.rstrip(".")) in norm(text) if text else False
        anywhere = [c for c, t in src.values() if norm(quote.rstrip(".")) in norm(t)]
        lines.append({"ev": quote, "src": idx, "cit": cit, "verbatim_in_cited": verb, "verbatim_somewhere": anywhere})
    rows.append({"id": o["id"], "group": o["group"], "lines": lines, "output": o["output"]})
(HERE / "verbatim_check.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
for r in rows:
    q = qs[r["id"]]
    print("=" * 90); print(r["group"], r["id"], "| KEY:", q["Expected Citation — VERIFIED KEY"]); print("Q:", q["Question (ask verbatim)"][:220]); print("KEY:", q["Key Answer Elements"][:330])
    print("OUT:", r["output"][:1400])
    for x in r["lines"]:
        if x["ev"] != "NOT IN SOURCES":
            print("   ->", x["cit"], "| verbatim_in_cited:", x["verbatim_in_cited"], "| somewhere:", x["verbatim_somewhere"])
