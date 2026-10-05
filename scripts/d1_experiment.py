"""D1 controlled experiment: Arm 0 production, Arm 1 numeric ordering (K1), Arm 2 K1 + part-level ceiling probe.

    python scripts/d1_experiment.py --set artifacts/diagnostics/model_probe/probe_set.json --arm 0|1|2

NO PRODUCTION SOURCE IS MODIFIED. Both interventions are injected at runtime, in this script only, by
monkey-patching the two call sites the forensic investigation identified:

  K1  (arms 1, 2)  `regulus.retrieval.lexical.order_evidence` - the name the retriever calls at
                   lexical.py:447. The wrapper calls the real production function first, then re-sorts
                   ONLY evidence whose tier is EXACT and which ties on (requirement order, ordinal), using
                   a numeric CFR key. Every other tier keeps production order untouched.

  CEIL (arm 2)     `regulus.rag.pipeline.select_evidence` - the name the pipeline calls at pipeline.py:341.
                   The wrapper inspects the plan: if and only if every requirement is part-level
                   (`reference.section is None`), it substitutes a ContextPolicy whose HARD ceilings are
                   raised (hard_max_results 24 -> 84, hard_max_total_chars 9000 -> 24000). Soft budgets
                   (max_results, max_chars_per_result, max_total_chars) are left exactly as production has
                   them. Any other plan gets the production policy object unchanged.

The raised char ceiling is required for the probe to mean anything: 84 sections of Part 111 render to
roughly 14k characters, so a 9,000-char ceiling would truncate at about 50 sections and the probe would
measure the char ceiling instead of the count ceiling. This is documented as part of the arm, and it is a
temporary runtime injection - no production default changes.

The benchmark keyed section is used ONLY after the answer exists, for measurement. Nothing in either patch
reads the benchmark.

Output: artifacts/diagnostics/d1_experiment/arm<N>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

_SEC_RE = re.compile(r"^(\d{1,4})\.(\d+)([a-zA-Z]*)")
FULL_HARD_MAX_RESULTS = 400     # arm 4: full sections arrive as one row per paragraph, so the count ceiling
FULL_PART_ROW_LIMIT = 4000      #        must not bind; the CHARACTER ceiling is the constrained resource
PART_HARD_MAX_RESULTS = 84      # covers Part 111's 84 live sections, the largest part in the probe
PART_HARD_MAX_CHARS = 24000     # 84 sections render to ~14k chars; headroom, still far inside the 40,960-token window


def numeric_cfr_key(section: str | None, paragraph: str, path_ordinal: int):
    """Regulatory numeric order. Never raises, which float() would: the corpus holds 12 alpha-suffixed
    sections ("184.1141a") and 8 ranges ("820.20-820.30"). An alpha suffix sorts after its bare number;
    a range sorts at its first endpoint, which is its regulatory position; anything unparseable sorts
    last, stably, rather than throwing."""
    m = _SEC_RE.match(section or "")
    if not m:
        return (1, 0, 0, "", section or "", paragraph, path_ordinal)
    return (0, int(m.group(1)), int(m.group(2)), m.group(3).lower(), "", paragraph, path_ordinal)


class PinnedBudget:
    """Transparent generator proxy that forces max_new_tokens to a per-question value.

    Arm 2 enlarges the evidence package, and the production budget policy is adaptive
    (`evidence_multiple` 1.4, `evidence_cap_fraction` 0.75, `hard_max_tokens` 2048), so a bigger
    package silently buys a bigger generation allowance. That would confound evidence composition
    with generation capacity. This pins the allowance to the value Arm 0 actually used for the same
    question, so the ONLY difference between the arms is which evidence survives selection.
    """

    def __init__(self, inner, budgets: dict[str, int]) -> None:
        self.inner, self.budgets = inner, budgets
        self.model, self.tokenizer = inner.model, inner.tokenizer
        self.qid: str | None = None
        self.requested: list[int | None] = []

    @property
    def calls(self):
        return self.inner.calls

    def generate(self, messages, max_new_tokens=None, on_text=None):
        self.requested.append(max_new_tokens)
        pinned = self.budgets.get(self.qid or "")
        return self.inner.generate(messages, max_new_tokens=pinned or max_new_tokens, on_text=on_text)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def install_k1():
    """Re-sort tied EXACT evidence into numeric CFR order; leave every other tier as production ordered it."""
    import regulus.retrieval.lexical as lex
    from regulus.retrieval.evidence import TIER_EXACT

    real = lex.order_evidence

    def patched(evidence, requirements):
        ordered = list(real(evidence, requirements))          # production order first
        order = {r.id: r.order for r in requirements}

        def group_key(e):
            ids = e.satisfies or ()
            first = min((order[i] for i in ids), default=len(order) + 1)
            ordinal = e.result.metadata.get("ordinal")
            return (first, int(ordinal) if isinstance(ordinal, int) else 0)

        out, i = [], 0
        while i < len(ordered):
            e = ordered[i]
            if e.tier != TIER_EXACT:
                out.append(e); i += 1; continue
            j, k = i, group_key(e)
            while j < len(ordered) and ordered[j].tier == TIER_EXACT and group_key(ordered[j]) == k:
                j += 1
            out.extend(sorted(ordered[i:j], key=lambda x: numeric_cfr_key(
                x.result.metadata.get("section"), x.result.metadata.get("paragraph_path") or "",
                int(x.result.metadata.get("ordinal") or 0))))
            i = j
        return out

    lex.order_evidence = patched
    return "K1: lexical.order_evidence wrapped; EXACT ties re-sorted by numeric CFR key"


def _full_part_sql():
    """ECFR_EXACT_PART with the `ordinal = 0` filter removed, so a whole-Part request returns EVERY
    paragraph of every section instead of only each section's first row. Derived from the production
    query by text surgery so the column list and filters stay in lockstep with it."""
    from regulus.retrieval import sql as rsql
    q = rsql.ECFR_EXACT_PART
    q2 = re.sub(r"\n\s*AND r\.ordinal = 0\b", "", q)
    assert q2 != q, "ECFR_EXACT_PART no longer contains the ordinal filter; revisit arm 4"
    q3 = q2.replace("ORDER BY r.section_number\n", "ORDER BY r.section_number, r.ordinal\n")
    assert q3 != q2, "ECFR_EXACT_PART ORDER BY changed; revisit arm 4"
    return q3


def install_full_sections():
    """Arm 4: whole-Part requests retrieve complete sections, not just paragraph 0."""
    import regulus.retrieval.lexical as lex

    full_sql = _full_part_sql()
    real = lex.LexicalRetriever.exact_cfr

    def patched(self, ref, filters, limit):
        if ref.title != "21" or ref.section is not None:
            return real(self, ref, filters, limit)
        rows = self.db.query(full_sql, {**self._ecfr_filter_params(filters),
                                        "part_number": ref.part, "limit": FULL_PART_ROW_LIMIT})
        return [self._ecfr_result(row, lex.METHOD_EXACT_CFR,
                                  lex.exact_score(row["match_kind"], row["ordinal"]),
                                  {"match_kind": row["match_kind"], "requested": ref.label})
                for row in rows]

    lex.LexicalRetriever.exact_cfr = patched
    return ("FULL: lexical.exact_cfr returns every paragraph of every section for whole-Part requests "
            f"(ordinal filter lifted, row limit {FULL_PART_ROW_LIMIT})")


def install_section_contiguous_order():
    """Arm 4 companion: keep a section's paragraphs together.

    Production orders EXACT evidence by (requirement, ordinal, key). With one row per section every
    ordinal is 0, so the effective order is the citation string. With full sections the ordinals run
    0..n and that same rule becomes PARAGRAPH-major - paragraph 0 of every section, then paragraph 1 of
    every section - which shreds the text. This restores section-major order.

    It deliberately keeps production's ASCII section order rather than numeric order, so arm 4 does not
    smuggle in K1: the only thing this changes is that paragraphs of one section stay contiguous.
    """
    import regulus.retrieval.lexical as lex
    from regulus.retrieval.evidence import TIER_EXACT

    real = lex.order_evidence

    def patched(evidence, requirements):
        ordered = list(real(evidence, requirements))
        order = {r.id: r.order for r in requirements}

        def key(e):
            ids = e.satisfies or ()
            first = min((order[i] for i in ids), default=len(order) + 1)
            md = e.result.metadata
            return (first, md.get("section") or "", int(md.get("ordinal") or 0))

        exact = sorted((e for e in ordered if e.tier == TIER_EXACT), key=key)
        return exact + [e for e in ordered if e.tier != TIER_EXACT]

    lex.order_evidence = patched
    return "ORDER: EXACT evidence ordered section-major (ASCII section, then paragraph ordinal)"


def install_ceiling_for(results: int, chars: int, label: str):
    """Raise the HARD ceilings for whole-part plans only. Soft budgets untouched."""
    import regulus.rag.pipeline as pipe

    real = pipe.select_evidence

    def patched(registry, policy=None, **kw):
        reqs = registry.plan.requirements
        part_level = bool(reqs) and all(r.reference.section is None for r in reqs)
        if part_level and policy is not None:
            policy = replace(policy, hard_max_results=results, hard_max_total_chars=chars)
        return real(registry, policy, **kw)

    pipe.select_evidence = patched
    return f"CEIL[{label}]: whole-part plans only get hard_max_results={results}, hard_max_total_chars={chars}"


def install_ceiling():
    """Raise the HARD ceilings for whole-part plans only. Soft budgets untouched."""
    import regulus.rag.pipeline as pipe

    real = pipe.select_evidence

    def patched(registry, policy=None, **kw):
        reqs = registry.plan.requirements
        part_level = bool(reqs) and all(r.reference.section is None for r in reqs)
        if part_level and policy is not None:
            policy = replace(policy, hard_max_results=PART_HARD_MAX_RESULTS, hard_max_total_chars=PART_HARD_MAX_CHARS)
        return real(registry, policy, **kw)

    pipe.select_evidence = patched
    return (f"CEIL: pipeline.select_evidence wrapped; whole-part plans only get "
            f"hard_max_results={PART_HARD_MAX_RESULTS}, hard_max_total_chars={PART_HARD_MAX_CHARS}")


REFUSE = re.compile(r"(does not exist|no such|not contain|not found|cannot (state|answer|find)|will not infer|outside|"
                    r"not covered|does not provide enough information|no provision)", re.I)
STOP = set("what does which require requires required requirement requirements must shall under that this with from part "
           "section about their there these those have when where into such each every apply applies the and for are not "
           "you your how many give list cite explain describe summarize summarise walk tell does do is it its on in of a "
           "an be by or if my our we can confirm so also including include any other".split())
words = lambda t: {w for w in re.findall(r"[a-z][a-z-]{3,}", (t or "").lower())} - STOP


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--arm", required=True, choices=["0", "1", "2", "3", "4"])
    ap.add_argument("--out", default=str(ROOT / "artifacts/diagnostics/d1_experiment"))
    ap.add_argument("--pin-budget-from", default=None,
                    help="arm JSON whose per-question generation budget this arm must reuse exactly")
    ap.add_argument("--only-ids", default=None, help="comma-separated question ids, run in this order")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    probe = json.loads(Path(args.set).read_text(encoding="utf-8"))
    if args.only_ids:
        want = [x.strip() for x in args.only_ids.split(",") if x.strip()]
        by_id = {it["id"]: it for it in probe}
        missing = [x for x in want if x not in by_id]
        if missing:
            raise SystemExit(f"--only-ids not in the probe set: {missing}")
        probe = [by_id[x] for x in want]          # run in the order given
    pinned_budgets: dict[str, int] = {}
    if args.pin_budget_from:
        src = json.loads(Path(args.pin_budget_from).read_text(encoding="utf-8"))
        pinned_budgets = {r["id"]: r["budget"] for r in src["rows"] if r.get("budget")}
        absent = [it["id"] for it in probe if it["id"] not in pinned_budgets]
        if absent:
            raise SystemExit(f"no recorded budget to pin for: {absent}")
        print(f"pinning generation budget from {args.pin_budget_from} (arm {src['arm']}) for {len(probe)} rows")

    patches = []
    if args.arm in ("1", "2"):
        patches.append(install_k1())
    if args.arm == "2":
        patches.append(install_ceiling())
    if args.arm == "3":
        # ceiling ONLY: production ordering, production ordinal=0 retrieval
        patches.append(install_ceiling_for(PART_HARD_MAX_RESULTS, PART_HARD_MAX_CHARS, "breadth"))
    if args.arm == "4":
        # same CHARACTER budget as arm 3, spent on depth instead of breadth
        patches.append(install_full_sections())
        patches.append(install_section_contiguous_order())
        patches.append(install_ceiling_for(FULL_HARD_MAX_RESULTS, PART_HARD_MAX_CHARS, "depth"))

    from model_probe_phase3 import RecordingGenerator
    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.remote_generator import load_generator
    from regulus.retrieval import Database
    from regulus.retrieval.factory import build_retriever
    from regulus.retrieval.references import parse_cfr_references
    from regulus.system_identity import configured_generation_config, configured_rag_config

    bench = {q.question_id: q for q in load_acceptance_benchmark()}
    settings = load_settings()
    settings.generation = configured_generation_config(settings)
    base = load_generator(settings, local_files_only=True)
    rec = RecordingGenerator(base, base.tokenizer, settings.generation.enable_thinking)
    gen = PinnedBudget(rec, pinned_budgets) if pinned_budgets else rec
    tok = base.tokenizer
    db = Database.from_env(); db.connect()
    cfg = configured_rag_config(settings)
    retriever, scope = build_retriever(db, cfg)
    pipe = RagPipeline(retriever, gen, cfg, scope_policy=scope)

    # how many paragraphs each section actually has, for "full section vs paragraph 0 only"
    def section_paragraph_count(sec: str) -> int:
        r = db.query("select count(*) n from cfr_records where section_number=%s", (sec,))
        return int(r[0]["n"]) if r else 0

    rows = []
    for i, item in enumerate(probe, start=1):
        qid = item["id"]; q = bench[qid]
        keyed = item.get("key_sections") or []          # measurement only; never used by retrieval or selection
        plan = plan_query(q.question)
        part_level = bool(plan.requirements) and all(r.reference.section is None for r in plan.requirements)
        before = len(rec.calls)
        if pinned_budgets:
            gen.qid = qid
            requested_before = len(gen.requested)
        t0 = time.perf_counter()
        outp = pipe.answer(q.question)
        requested_budget = (gen.requested[requested_before] if pinned_budgets and len(gen.requested) > requested_before else None)
        calls = rec.calls[before:]
        c = calls[0] if calls else None
        m = outp.metadata
        srcs = list(outp.context.sources)
        sec_of = []
        for s in srcs:
            refs = [x for x in parse_cfr_references(s.result.citation.label) if x.title == "21"]
            sec_of.append(refs[0].section if refs and refs[0].section else None)
        tiers = [((c["user"].split(f"SOURCE {n}\n")[1].split("\n")[0]) if c and f"SOURCE {n}\n" in c["user"] else None)
                 for n in range(1, len(srcs) + 1)]
        rank = next((n + 1 for n, s in enumerate(sec_of) if s in keyed), None)
        src_tokens = [len(tok(s.text)["input_ids"]) for s in srcs]
        total_tokens = sum(src_tokens)
        before_tokens = sum(src_tokens[: rank - 1]) if rank else None
        keyed_share = round(100 * src_tokens[rank - 1] / total_tokens, 2) if rank and total_tokens else None
        paras_present = {}
        for s in keyed:
            present = sum(1 for x in sec_of if x == s)
            paras_present[s] = {"paragraphs_in_prompt": present, "paragraphs_in_section": section_paragraph_count(s)}
        raw = (c and c["raw_response"]) or ""
        final = outp.answer
        is_trap = any(t in (q.expected_citation_draft or "").upper() for t in
                      ("NO SUCH", "FALSE PREMISE", "NOT COVERED", "REPEALED", "TEMPORAL TRAP", "MUST DECLINE",
                       "MUST QUALIFY", "MUST REFUSE", "OUT OF SCOPE", "AMBIGUOUS"))
        kw = words(q.key_answer_elements)
        recall_raw = round(len(kw & words(raw)) / len(kw), 3) if kw else 0.0
        recall_final = round(len(kw & words(final)) / len(kw), 3) if kw else 0.0
        mech = 1 if (bool(REFUSE.search(raw)) if is_trap else recall_raw >= 0.5) else 0
        rows.append({
            "arm": args.arm, "id": qid, "type": q.question_type, "part_level_plan": part_level,
            "keyed_sections": keyed, "requirements": [r.reference.canonical for r in plan.requirements],
            # evidence metrics
            "keyed_present": bool(rank), "keyed_rank": rank, "n_sources": len(srcs),
            "evidence_chars": sum(len(s.text) for s in srcs), "evidence_tokens": total_tokens,
            "tokens_before_keyed": before_tokens, "keyed_token_share_pct": keyed_share,
            "keyed_paragraph_coverage": paras_present,
            "sections": sec_of, "tiers": tiers,
            "prompt_tokens": c and c["prompt_tokens_counted"], "budget": c and c["generation_budget_passed"],
            "budget_pinned_to": pinned_budgets.get(qid), "budget_adaptive_requested": requested_budget,
            "generated_tokens": c and c["generated_tokens"], "finished_with_eos": c and c["finished_with_eos"],
            "stop_reason": c and c["stop_reason"],
            # answer metrics, existing diagnostic scoring only
            "recall_raw": recall_raw, "recall_final": recall_final, "mechanical_pass": mech,
            "scoring_mode": "trap_refusal" if is_trap else "substantive_recall",
            "cites_keyed_section": bool(keyed) and any(s in raw for s in keyed),
            "has_any_citation": bool(re.search(r"\[\d+\]", raw)),
            "model_called": outp.model_called, "answerability": (m.get("answerability") or {}).get("state"),
            "coverage_state": (m.get("coverage") or {}).get("state"),
            "repair": (m.get("validation") or {}).get("repair"), "validation_final": (m.get("validation") or {}).get("final", {}).get("status"),
            "raw": raw, "final_answer": final,
            "prompt_sha256": c and c["prompt_sha256"], "seconds": round(time.perf_counter() - t0, 1),
        })
        print(f"{i:3}/{len(probe)} arm{args.arm} {qid:8} part_level={str(part_level):5} src={len(srcs):2} "
              f"keyed_rank={str(rank):4} tok={total_tokens:5} recall={recall_raw:.2f} pass={mech} {rows[-1]['seconds']:5}s", flush=True)
        (out / f"arm{args.arm}.json").write_text(json.dumps(
            {"arm": args.arm, "patches": patches,
             "identity": {"model": base.describe(), "config_fingerprint": cfg.to_dict(),
                          "system_prompt_sha256": hashlib.sha256(
                              __import__("regulus.rag.generation", fromlist=["x"]).GROUNDED_SYSTEM_PROMPT.encode()).hexdigest()},
             "rows": rows}, indent=1, default=str), encoding="utf-8")
    db.close()
    print("patches:", patches)
    print("wrote", out / f"arm{args.arm}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
