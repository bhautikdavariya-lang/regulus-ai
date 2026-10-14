"""Phase 1: trace "What does 21 CFR 312.32 require?" answered with (c)(1) only, through production."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine_harness import ask, run_pipeline  # noqa: E402

Q = "What does 21 CFR 312.32 require?"


def main():
    from regulus.rag.shape_validation import check_shape
    # (c)(1) verbatim with its marker; the marker is chosen from the real package below
    out0, _ = run_pipeline(Q, "placeholder")
    src = {s.citation: s for s in out0.package.sources}
    c1 = src["21 CFR 312.32(c)(1)"]
    answer = c1.text.split(". ", 1)[1].strip() + f" [{c1.index}]"
    out, assessment = run_pipeline(Q, answer)
    pkg, plan = out.package, out.package.answer_plan
    d = assessment.to_dict()
    print("1. QUESTION INTERPRETATION / ANSWER PLAN")
    print("   shape:", plan.shape.mode, "| exhaustive:", plan.shape.exhaustive, "| requested:", pkg.requirements)
    print("   groups (key, head, members):")
    for g in plan.groups:
        print(f"     {g.label:<22} kind={g.kind:<12} members={[ (i, pkg.sources[i-1].citation.replace('21 CFR 312.32','')) for i in g.members]}")
    print("\n2. EVIDENCE:", [(s.index, s.citation.replace('21 CFR 312.32', '')) for s in pkg.sources])
    print("\n3. GENERATED (scripted):", answer[:120], "...")
    md = out.metadata
    print("\n4. POST-PROCESSING")
    print("   validation initial codes:", (md.get("validation_initial") or {}).get("codes") if isinstance(md.get("validation_initial"), dict) else md.get("validation_initial_codes"))
    print("   repair:", md.get("repair"))
    findings, info = check_shape(answer, pkg, plan)
    print("   shape findings on the GENERATED answer:", [(f.code, f.detail[:90]) for f in findings if f.severity == "error"])
    print("     shape info:", {k: v for k, v in info.items() if "group" in k or "material" in k})
    print("\n   DELIVERED ANSWER:\n", out.answer)
    findings2, info2 = check_shape(out.answer, pkg, plan)
    print("\n   shape findings on the DELIVERED answer:", [(f.code, f.detail[:90]) for f in findings2 if f.severity == "error"])
    print("\n5/6/7. EVALUATION")
    print("   verdict:", d["answer_verdict"]["verdict"], "| score:", d["accuracy"])
    for x in d["dimensions"]:
        print(f"     {x['dimension']:<24} {x['state']:<16} {str(x.get('detail'))[:150]}")
    for c in d["checked"]["claims"]:
        print(f"     claim: {c['support']:<22} cites/aligned={[e.get('citation') for e in c.get('evidence') or []][:1]} :: {c['claim'][:90]}")
    Path(sys.argv[1]).write_text(json.dumps({"answer": answer, "delivered": out.answer, "assessment": d,
                                             "shape_info": info2, "metadata_keys": sorted(md)}, indent=1, default=str))


if __name__ == "__main__":
    main()
