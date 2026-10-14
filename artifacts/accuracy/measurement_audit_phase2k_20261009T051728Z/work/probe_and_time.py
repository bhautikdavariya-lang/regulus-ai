"""READ-ONLY: (1) JR qualifier-conflict probe over frozen claims x real negated-relative corpus sentences;
(2) compare() runtime over every unique recorded comparison, for the loaded regulus.accuracy."""
import json, sys, time, statistics
from collections import Counter
from regulus.accuracy import operators as OP
W, NAME = sys.argv[1] + "/work/", sys.argv[2]
H = json.load(open(W + "h_current.json"))
pairs = sorted({(c["claim"], c["evidence"], c["authority"]) for c in H["calls"]})
runs = []
for _ in range(3):
    t = time.perf_counter()
    for c, e, a in pairs: OP.compare(c, e, authority=a)
    runs.append((time.perf_counter() - t) / len(pairs) * 1000)
res = {"variant": NAME, "pairs": len(pairs), "ms_per_compare_runs": runs, "ms_per_compare_median": statistics.median(runs)}
if NAME == "JR":
    claims = sorted({c for c, _, _ in pairs})
    corpus = sorted({h["sentence"] for h in json.load(open("artifacts/accuracy/measurement_audit_phase2i_20261009T044401Z/work/corpus_rel_negations.json"))})
    flags = []
    for c in claims:
        for e in corpus:
            x = OP._p2k_jr_conflict(c, e)
            if x: flags.append((c, e, list(x)))
    res["probe_pairs"] = len(claims) * len(corpus); res["probe_conflicts"] = len(flags)
    res["probe_keys"] = Counter(x[0] for _, _, x in flags).most_common(15)
    res["probe_examples"] = flags[:12]
json.dump(res, open(W + f"probe_time_{NAME}.json", "w"), indent=1, ensure_ascii=False)
print(NAME, f"compare median {res['ms_per_compare_median']:.3f} ms over {len(pairs)} pairs", ("| probe conflicts %d of %d, keys %s" % (res["probe_conflicts"], res["probe_pairs"], res["probe_keys"])) if NAME == "JR" else "")
