"""Analyse the three D1 arms and emit the deliverable tables. Read-only."""
from __future__ import annotations
import json, sys, collections
from pathlib import Path
from math import comb

D = Path("artifacts/diagnostics/d1_experiment")
AVAIL = [n for n in (0, 1, 2) if (D / f"arm{n}.json").exists()]
ARMS = {n: json.load(open(D / f"arm{n}.json")) for n in AVAIL}
if len(ARMS) < 3:
    print(f"!! only arms {AVAIL} present - arm 2 still running; tables below are partial\n")
R = {n: {r["id"]: r for r in a["rows"]} for n, a in ARMS.items()}
IDS = [r["id"] for r in ARMS[0]["rows"]]
PL = [i for i in IDS if R[0][i]["part_level_plan"]]
NPL = [i for i in IDS if not R[0][i]["part_level_plan"]]
KEYED = [i for i in PL if R[0][i]["keyed_sections"]]


def mcnemar(a, b, rows):
    """Exact two-sided McNemar on paired binary mechanical_pass."""
    n01 = sum(1 for i in rows if not R[a][i]["mechanical_pass"] and R[b][i]["mechanical_pass"])
    n10 = sum(1 for i in rows if R[a][i]["mechanical_pass"] and not R[b][i]["mechanical_pass"])
    n = n01 + n10
    if n == 0:
        return n01, n10, 1.0
    k = min(n01, n10)
    p = min(1.0, 2 * sum(comb(n, j) for j in range(k + 1)) / 2 ** n)
    return n01, n10, p


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def sec(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


sec("FREEZE VERIFICATION")
print("identity identical across arms:", all(ARMS[n]["identity"] == ARMS[AVAIL[0]]["identity"] for n in AVAIL))
print("question ids and order identical:", all([r["id"] for r in ARMS[n]["rows"]] == IDS for n in AVAIL[1:]))
print("rows per arm:", {n: len(ARMS[n]["rows"]) for n in AVAIL})
for n in AVAIL:
    print(f"  arm{n} patches: {ARMS[n]['patches']}")
print(f"\n{len(NPL)} non-part-level control rows should be bit-identical in all three arms:")
for n in AVAIL[1:]:
    print(f"  arm0 vs arm{n}: prompt {all(R[0][i]['prompt_sha256']==R[n][i]['prompt_sha256'] for i in NPL)}"
          f"  raw {all(R[0][i]['raw']==R[n][i]['raw'] for i in NPL)}"
          f"  final {all(R[0][i]['final_answer']==R[n][i]['final_answer'] for i in NPL)}")
print(f"\n{len(PL)} part-level rows, prompt changed vs arm0:",
      {n: sum(1 for i in PL if R[0][i]["prompt_sha256"] != R[n][i]["prompt_sha256"]) for n in AVAIL[1:]})

sec("DELIVERABLE 4 - EVIDENCE METRICS (part-level rows, n=%d; keyed subset n=%d)" % (len(PL), len(KEYED)))
hdr = f"{'metric':46} {'arm0':>10} {'arm1':>10} {'arm2':>10}"
print(hdr); print("-" * len(hdr))
def row(label, fn, rows=None, fmt="{:10.2f}"):
    rows = rows if rows is not None else PL
    print(f"{label:46} " + " ".join(fmt.format(fn(n, rows)) if n in R else f"{'?':>10}" for n in (0,1,2)))
row("keyed section present (count)", lambda n, r: sum(1 for i in r if R[n][i]["keyed_present"]), KEYED, "{:10.0f}")
row("keyed present (% of keyed rows)", lambda n, r: 100 * mean(bool(R[n][i]["keyed_present"]) for i in r), KEYED)
row("mean keyed rank (present only)", lambda n, r: mean(R[n][i]["keyed_rank"] for i in r if R[n][i]["keyed_rank"]), KEYED)
row("keyed rank = 1 (count)", lambda n, r: sum(1 for i in r if R[n][i]["keyed_rank"] == 1), KEYED, "{:10.0f}")
row("mean sources in prompt", lambda n, r: mean(R[n][i]["n_sources"] for i in r))
row("mean evidence chars", lambda n, r: mean(R[n][i]["evidence_chars"] for i in r), None, "{:10.0f}")
row("mean evidence tokens", lambda n, r: mean(R[n][i]["evidence_tokens"] for i in r), None, "{:10.0f}")
row("mean prompt tokens", lambda n, r: mean(R[n][i]["prompt_tokens"] for i in r), None, "{:10.0f}")
row("mean tokens before keyed section", lambda n, r: mean(R[n][i]["tokens_before_keyed"] for i in r if R[n][i]["keyed_present"]), KEYED, "{:10.0f}")
row("mean keyed token share %", lambda n, r: mean(R[n][i]["keyed_token_share_pct"] for i in r if R[n][i]["keyed_present"]), KEYED)
row("max keyed paragraphs in prompt", lambda n, r: max((v["paragraphs_in_prompt"] for i in r for v in (R[n][i]["keyed_paragraph_coverage"] or {}).values()), default=0), KEYED, "{:10.0f}")
row("mean keyed paragraphs in prompt", lambda n, r: mean(v["paragraphs_in_prompt"] for i in r for v in (R[n][i]["keyed_paragraph_coverage"] or {}).values()), KEYED)
row("mean keyed paragraphs in section", lambda n, r: mean(v["paragraphs_in_section"] for i in r for v in (R[n][i]["keyed_paragraph_coverage"] or {}).values()), KEYED)
row("mean seconds per question", lambda n, r: mean(R[n][i]["seconds"] for i in r))

sec("DELIVERABLE 5 - ANSWER QUALITY METRICS")
for label, rows in (("all 36 rows", IDS), ("part-level rows", PL), ("keyed part-level rows", KEYED), ("control (non-part-level)", NPL)):
    print(f"\n-- {label} (n={len(rows)})")
    print(hdr); print("-" * len(hdr))
    row("mechanical pass (count)", lambda n, r: sum(R[n][i]["mechanical_pass"] for i in r), rows, "{:10.0f}")
    row("mechanical pass rate %", lambda n, r: 100 * mean(R[n][i]["mechanical_pass"] for i in r), rows)
    row("mean key recall, raw output", lambda n, r: mean(R[n][i]["recall_raw"] for i in r), rows, "{:10.3f}")
    row("mean key recall, final answer", lambda n, r: mean(R[n][i]["recall_final"] for i in r), rows, "{:10.3f}")
    row("cites the keyed section (count)", lambda n, r: sum(1 for i in r if R[n][i]["cites_keyed_section"]), rows, "{:10.0f}")
    row("has any citation (count)", lambda n, r: sum(1 for i in r if R[n][i]["has_any_citation"]), rows, "{:10.0f}")
    row("model was called (count)", lambda n, r: sum(1 for i in r if R[n][i]["model_called"]), rows, "{:10.0f}")
    row("answer withheld/unvalidated (count)", lambda n, r: sum(1 for i in r if R[n][i]["validation_final"] not in (None, "ok", "complete")), rows, "{:10.0f}")
    row("mean generated tokens", lambda n, r: mean(R[n][i]["generated_tokens"] or 0 for i in r), rows, "{:10.0f}")
    row("finished on EOS (count)", lambda n, r: sum(1 for i in r if R[n][i]["finished_with_eos"]), rows, "{:10.0f}")

sec("PAIRED SIGNIFICANCE (exact McNemar on mechanical_pass)")
for label, rows in (("all 36", IDS), ("part-level 20", PL), ("keyed part-level 18", KEYED)):
    pairs = [(0, 1, "arm0 -> arm1 (K1)"), (0, 2, "arm0 -> arm2 (K1+ceiling)"), (1, 2, "arm1 -> arm2 (ceiling alone)")]
    for a, b, nm in [x for x in pairs if x[0] in AVAIL and x[1] in AVAIL]:
        n01, n10, p = mcnemar(a, b, rows)
        print(f"  {label:20} {nm:28} gained {n01}  lost {n10}  p = {p:.3f}")

sec("DELIVERABLE 6 - QUESTION-BY-QUESTION DELTA (part-level rows)")
h = (f"{'id':8} {'type':15} {'keyed':24} | {'rank0':>5} {'rank1':>5} {'rank2':>5} | "
     f"{'n0':>3} {'n1':>3} {'n2':>3} | {'rec0':>5} {'rec1':>5} {'rec2':>5} | {'p0':>2} {'p1':>2} {'p2':>2}")
print(h); print("-" * len(h))
for i in PL:
    r0 = R[0][i]
    print(f"{i:8} {r0['type'][:15]:15} {(','.join(r0['keyed_sections']) or '-')[:24]:24} | "
          + " ".join(f"{str(R[n][i]['keyed_rank'] or '-'):>5}" if n in R else f"{'?':>5}" for n in (0,1,2)) + " | "
          + " ".join(f"{R[n][i]['n_sources']:3}" if n in R else "  ?" for n in (0,1,2)) + " | "
          + " ".join(f"{R[n][i]['recall_raw']:5.2f}" if n in R else "    ?" for n in (0,1,2)) + " | "
          + " ".join(f"{R[n][i]['mechanical_pass']:2}" if n in R else " ?" for n in (0,1,2)))

sec("DELIVERABLE 7 - RESCUED / REGRESSED / STUCK")
def cls(i):
    return [R[n][i]["mechanical_pass"] if n in R else 0 for n in (0, 1, 2)]
buckets = collections.defaultdict(list)
for i in PL:
    p0, p1, p2 = cls(i)
    pres = [bool(R[n][i]["keyed_present"]) if n in R else False for n in (0, 1, 2)]
    if not p0 and p1: buckets["rescued by K1"].append(i)
    if p0 and not p1: buckets["regressed by K1"].append(i)
    if 2 in R:
        if not p0 and not p1 and p2: buckets["rescued only by K1+ceiling"].append(i)
        if p0 and not p2: buckets["regressed by K1+ceiling"].append(i)
        if not p0 and not p1 and not p2:
            buckets["wrong in all three arms"].append(i)
            if all(pres): buckets["  ...of which keyed section present in ALL arms"].append(i)
        if pres[2] and not p2: buckets["keyed present in arm2 but still wrong"].append(i)
for k in ("rescued by K1", "regressed by K1", "rescued only by K1+ceiling", "regressed by K1+ceiling",
          "wrong in all three arms", "  ...of which keyed section present in ALL arms",
          "keyed present in arm2 but still wrong"):
    v = buckets.get(k, [])
    print(f"{k:48} {len(v):2}  {', '.join(v) if v else '-'}")

sec("EVIDENCE PRESENT vs ANSWER CORRECT (decoupling check)")
print(f"{'arm':6} {'keyed present & pass':>22} {'keyed present & fail':>22} {'absent & pass':>15} {'absent & fail':>15}")
for n in AVAIL:
    pp = sum(1 for i in KEYED if R[n][i]["keyed_present"] and R[n][i]["mechanical_pass"])
    pf = sum(1 for i in KEYED if R[n][i]["keyed_present"] and not R[n][i]["mechanical_pass"])
    ap = sum(1 for i in KEYED if not R[n][i]["keyed_present"] and R[n][i]["mechanical_pass"])
    af = sum(1 for i in KEYED if not R[n][i]["keyed_present"] and not R[n][i]["mechanical_pass"])
    print(f"arm{n:<3} {pp:>22} {pf:>22} {ap:>15} {af:>15}")
print("\nRank-vs-quality, rows where the keyed section is present in both arm0 and arm1:")
both = [i for i in KEYED if R[0][i]["keyed_present"] and R[1][i]["keyed_present"]]
for i in both:
    d = (R[1][i]["keyed_rank"] or 0) - (R[0][i]["keyed_rank"] or 0)
    print(f"  {i:8} rank {R[0][i]['keyed_rank']} -> {R[1][i]['keyed_rank']} ({d:+d})  "
          f"recall {R[0][i]['recall_raw']:.2f} -> {R[1][i]['recall_raw']:.2f} "
          f"({R[1][i]['recall_raw']-R[0][i]['recall_raw']:+.2f})  pass {R[0][i]['mechanical_pass']} -> {R[1][i]['mechanical_pass']}")
imp = [i for i in both if (R[1][i]["keyed_rank"] or 99) < (R[0][i]["keyed_rank"] or 99)]
print(f"\n  rank improved on {len(imp)} rows: {', '.join(imp)}")
print(f"    of those, recall improved on {sum(1 for i in imp if R[1][i]['recall_raw']>R[0][i]['recall_raw'])}, "
      f"unchanged on {sum(1 for i in imp if abs(R[1][i]['recall_raw']-R[0][i]['recall_raw'])<1e-9)}, "
      f"fell on {sum(1 for i in imp if R[1][i]['recall_raw']<R[0][i]['recall_raw'])}")
print(f"    mechanical pass changed on {sum(1 for i in imp if R[1][i]['mechanical_pass']!=R[0][i]['mechanical_pass'])} of {len(imp)}")
