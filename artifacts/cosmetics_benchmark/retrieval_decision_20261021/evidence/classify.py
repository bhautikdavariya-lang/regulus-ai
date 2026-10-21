"""One primary failure category per question (no double counting), from saved evidence only:
Step 2A matrix (paragraph coverage, model-independent), Step 2B cause table (why evidence was missing),
Step 6 arm A (Qwen3-1.7B baseline) blind verdicts and delivery. Read-only; prints JSON."""
import json, re, sys
from collections import Counter

S8, ROOT = sys.argv[1], sys.argv[2]
RUN = ROOT + "/artifacts/cosmetics_benchmark/step6_q17_ab_20261021T055124Z"
ids = [q["ID"] for q in json.load(open(RUN + "/arm_A_switch_off/selection.json"))["questions"]]

# ---- Step 2A matrix rows: | # | ID | Label | Ans | Ret/Prompt/¶ | Corpus | Req. drop | Irrel | Con/Om/Cit | Validator | Primary | ...
m2a = {}
for line in open(S8 + "/step2a_report.md", encoding="utf-8"):
    c = [x.strip() for x in line.split("|")]
    if len(c) > 12 and c[2] in ids:
        m2a[c[2]] = {"cov": c[5].split("/")[-1] if "/" in c[5] else c[5], "rpp": c[5], "corpus": c[6], "drop": c[7], "primary_2a": c[11]}
assert len(m2a) == 100, len(m2a)

# ---- Step 2B cause table (abbreviated ids resolved against the question set, restricted to coverage none)
rows = {}
for line in open(S8 + "/step2b_report.md", encoding="utf-8"):
    c = [x.strip() for x in line.split("|")]
    if len(c) > 4 and re.match(r"\*?\*?(Not generated|Ranked out|Context-budget|Corpus)", c[1]):
        rows[c[1].replace("**", "")] = c[3]
def resolve(tok, pool):
    tok = tok.strip().strip("*").strip()
    tok = tok[len("COS-"):] if tok.startswith("COS-") else tok
    if not tok or tok.startswith("All "):
        return None
    full = [i for i in pool if i == tok or i == "COS-" + tok or i.startswith("COS-" + tok + "-")]
    if tok.startswith("UC-"):
        full = [tok] if tok in pool else []
    if len(full) != 1:
        raise SystemExit(f"cannot resolve {tok!r}: {full}")
    return full[0]
none_pool = [i for i in ids if m2a[i]["cov"] in ("none",)]
cause2b = {}
h1 = None
for name, cell in rows.items():
    if name.startswith("Corpus"):
        continue
    if "Part 73" in cell:
        h1 = name          # resolved after the explicit rows: the Part 73 questions no other row names
        continue
    for tok in re.split(r",\s*", cell):
        i = resolve(tok, none_pool)
        if i:
            assert i not in cause2b, i
            cause2b[i] = name
p73 = [i for i in none_pool if i.startswith("COS-73.") and i not in cause2b]
assert h1 and len(p73) == 9, p73
cause2b.update({i: h1 for i in p73})

# ---- Step 6 arm A
an = json.load(open(RUN + "/scoring/analysis.json"))
v, pq = an["verdicts"], an["per_question"]

def category(i):
    cov, prim = m2a[i]["cov"], m2a[i]["primary_2a"]
    if cov.startswith("statute"):
        return "G statute-only key (FD&C Act text not in corpus)"
    if cov == "none":
        c = cause2b.get(i, "?")
        if c.startswith("Not generated"):
            return "B exists, not retrieved (no leg generated it)"
        if c.startswith("Ranked out"):
            return "C retrieved by a leg but ranked/capped out before the registry"
        if c.startswith("Context-budget"):
            return "D in registry, dropped by the context budget"
        return "? unclassified"
    # some required evidence reached the prompt
    if cov == "part" and prim == "EI":
        return "B2 exists, required paragraph not retrieved (rest of evidence present)"
    return "E evidence reached the model; 1.7B answer is the limit"

out = {}
for i in ids:
    out[i] = {"cat": category(i), "cov": m2a[i]["cov"], "primary_2a": m2a[i]["primary_2a"], "cause_2b": cause2b.get(i),
              "A_category": v[i]["A"]["category"], "A_kind": pq[i]["kind"]["A"], "A_sub": v[i]["A"]["sub"]}
cats = Counter(x["cat"] for x in out.values())
print(json.dumps({"counts": dict(sorted(cats.items())),
                  "by_cat": {c: sorted(i for i in ids if out[i]["cat"] == c) for c in sorted(cats)},
                  "E_outcomes": dict(Counter(out[i]["A_kind"] + " -> " + out[i]["A_category"] for i in ids if out[i]["cat"].startswith("E"))),
                  "B2_outcomes": dict(Counter(out[i]["A_kind"] + " -> " + out[i]["A_category"] for i in ids if out[i]["cat"].startswith("B2"))),
                  "outcomes_by_cat": {c: dict(Counter(out[i]["A_category"] for i in ids if out[i]["cat"] == c)) for c in sorted(cats)},
                  "withheld_A": sorted(i for i in ids if out[i]["A_kind"] == "withheld"),
                  "cov_counts": dict(Counter(x["cov"] for x in out.values())),
                  "cause2b_count": len(cause2b)}, indent=1))
json.dump(out, open(S8 + "/classification.json", "w"), indent=1)
