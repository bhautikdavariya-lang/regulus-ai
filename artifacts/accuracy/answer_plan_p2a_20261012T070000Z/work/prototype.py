"""Prototype of the value plan, run over all 314 packages WITHOUT touching src/: where would it fire,
and what would it say? Reuses prompts.py's pipeline setup; no model, no generation."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))
from prompts import PROBES, Stub  # noqa: E402

NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|sixty|ninety)"
PERIOD_RE = re.compile(rf"\b({NUM})[\s-]+((?:calendar|working|business)[\s-]+)?(days?|weeks?|months?|years?|hours?)\b", re.I)
VALUE_WORDS = {"deadline", "deadlines", "timeframe", "timeframes", "time", "limit", "limits", "timeline", "timelines",
               "quickly", "soon", "long", "often", "rapidly", "promptly", "calendar-day", "calendar", "day", "days",
               "period", "periods", "frequency", "frequently", "within", "many", "how"}


_LEAD_TOKENS = re.compile(r"^\s*(?:\([A-Za-z0-9]{1,4}\)\s*)+")
_HEAD = re.compile(r"^([A-Z][A-Za-z ,'\u2014-]{1,90}?)\.\s")


def paragraph_heading(text):
    """The paragraph's own heading after ANY designation, "(c)(1) IND safety reports." included."""
    body = _LEAD_TOKENS.sub("", text or "", count=1)
    if body == (text or ""):
        return None
    m = _HEAD.match(body)
    h = m.group(1).strip() if m else None
    return h if h and 1 <= len(h.split()) <= 10 else None


def stem(w): return re.sub(r"[^a-z]", "", w.lower())[:5]


def periods(text):
    out = []
    for m in PERIOD_RE.finditer(text or ""):
        unit = m.group(3).lower().rstrip("s")
        kind = (m.group(2) or "").strip().lower().replace("-", " ")
        v = f"{m.group(1).lower()} {kind + ' ' if kind else ''}{unit}s"
        if v not in out:
            out.append(v)
    return out


def value_plan(question, shape, sources):
    from regulus.planning.shape import MODE_FOCUSED
    from regulus.rag.answer_plan import extract_heading
    from regulus.rag.evidence_values import selection_value_kind
    from regulus.retrieval.evidence import TIER_EXACT
    kind = selection_value_kind(question)
    if shape is None or shape.mode != MODE_FOCUSED or kind not in ("deadline", "duration_or_frequency"):
        return {"fires": False, "why": "not a focused period question"}
    exact = [s for s in sources if s.tier == TIER_EXACT and s.corpus == "ecfr"]
    first = {}
    for s in exact:
        for v in periods(s.text):
            first.setdefault(v, s)
    if len(first) < 2:
        return {"fires": False, "why": f"{len(first)} distinct period(s)"}
    entries = [(v, s.index, paragraph_heading(s.text)) for v, s in first.items()]
    if any(h is None for _, _, h in entries):
        return {"fires": False, "why": "a period has no headed source", "entries": entries}
    section_heading = " ".join({s.heading or "" for s in exact})
    umbrella = {stem(w) for w in re.findall(r"[A-Za-z][A-Za-z-]+", section_heading)}
    cond = [t for t in shape.focus_terms if t not in VALUE_WORDS and stem(t) not in umbrella]
    named = []
    if cond:
        for v, i, h in entries:
            hs = {stem(w) for w in re.findall(r"[A-Za-z][A-Za-z-]+", h)}
            share = sum(1 for t in cond if stem(t) in hs) / len(cond)
            if share >= 0.6:
                named.append((v, i, h))
    if len(named) == 1:
        return {"fires": False, "why": "narrowed to one condition: prompt unchanged", "narrowed": named, "cond": cond}
    return {"fires": True, "entries": entries, "cond": cond, "umbrella": sorted(umbrella)}


def main():
    from regulus.config import load_settings
    from regulus.evaluation.acceptance_benchmark import DEFAULT_WORKBOOK, load_acceptance_benchmark
    from regulus.planning import plan_query
    from regulus.rag import RagPipeline
    from regulus.rag.generation import build_package
    from regulus.retrieval import Database, Filters, LexicalRetriever
    from regulus.retrieval.factory import build_retriever
    from regulus.system_identity import configured_rag_config
    from dataclasses import replace
    settings = load_settings(); db = Database.from_env(); db.connect()
    config = replace(configured_rag_config(settings), top_k=8)
    retriever, scope = build_retriever(db, config, lexical=LexicalRetriever(db))
    pipeline = RagPipeline(retriever, Stub(), config, scope_policy=scope)
    cases = [(q.question_id, q.question) for q in load_acceptance_benchmark(ROOT / DEFAULT_WORKBOOK)] + PROBES
    res = {}
    for qid, question in cases:
        plan = pipeline.complete_plan(plan_query(question)); shape, analysis = pipeline.question_view(plan)
        out = retriever.run_plan(plan, corpus=config.corpus, top_k=config.top_k, filters=Filters())
        bundle, coverage, sel = pipeline.build_bundle(out.response, out.registry, shape, question)
        if sel is None or coverage is None:
            res[qid] = {"fires": False, "why": "no package"}; continue
        pkg = build_package(plan, coverage, sel, notes=bundle.notes, budget=pipeline.config.generation_budget,
                            answer_shape=shape, question_analysis=analysis)
        res[qid] = {"question": question, **value_plan(question, shape, pkg.sources)}
    db.close()
    Path(sys.argv[1]).write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    bench = [k for k in res if not k.startswith(("P", "C-")) or k[1:2] == "-" and k[2:].isdigit() or k[:2] in ("P-",) and k[2:].isdigit()]
    fired = [k for k, v in res.items() if v.get("fires")]
    print("FIRES on:", fired)
    for k, v in res.items():
        if k.startswith(("P1", "P2", "P3", "P4", "P5", "C-")) and not k[2:].isdigit():
            print(f"  {k:<14} fires={str(v.get('fires')):<5} {v.get('why','')} cond={v.get('cond')} "
                  f"entries={[(e[0], e[1], e[2]) for e in v.get('entries', [])] or v.get('narrowed')}")


if __name__ == "__main__":
    main()
