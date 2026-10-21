"""Experimental advanced retrieval, stages B-F (2026-10-21). OFF unless an AdvancedRetrieval is passed to RagPipeline.

Measured in the earlier programmes of 2026-10-20: every change that REORDERED the evidence inside the fixed 3,600
character context (agreement promotion, slot sharing, coverage-first ordering, decomposition, compact packing)
exchanged one required provision for another. So this stage never touches the base selection. It plans the
question (regulus.planning.regulatory_plan), checks which planned element no selected source addresses, and only for
those gathers candidates and appends the best one in a small bounded reserve, inside the existing hard ceilings. A
question whose every element is covered gets exactly the evidence it got before.

Stages, each behind its own flag (all False by default):

    structure   (D) a selected lead-in ("Petitions shall include the following data ...:") completed with its own
                    subparagraphs
    xref        (B) the provisions the selected eCFR sources explicitly cite (cfr_cross_references, one hop)
    semantic    (B) the existing local semantic index, per uncovered element (no new embeddings)
    iterate     (E) one targeted lexical search per uncovered element (at most ITERATE_MAX_SEARCHES), its rows kept
                    only when their CFR part is one the question's own candidates come from
    fusion      (C) reciprocal rank fusion across the legs; eCFR always before guidance, Title 21 only
    gap_fill    (F) append, per uncovered element, the best candidate that addresses it (GAP_RESERVE_CHARS,
                    GAP_MAX_SOURCES, hard ceilings)

Never for a question about another agency's rules (the plan's non_fda) or one that names a provision (exact lookup
and its own coverage handle those). Every decision is in the trace (Selection.diagnostics["advanced"]).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from regulus.planning.regulatory_plan import PlanElement, RegulatoryPlan, build_regulatory_plan
from regulus.retrieval import sql
from regulus.retrieval.evidence import TIER_DISCOVERY, Evidence, EvidenceRegistry
from regulus.retrieval.models import METHOD_CROSS_REFERENCE, METHOD_EXACT_CFR, RetrievalResult

FLAGS = ("structure", "xref", "semantic", "iterate", "fusion", "gap_fill")
GAP_RESERVE_CHARS = 1500
GAP_MAX_SOURCES = 3
ITERATE_MAX_SEARCHES = 2
LEG_CANDIDATES = 8
CHILD_LIMIT = 8
RRF_K = 60
SEMANTIC_FLOOR = 0.75
CORROBORATING = 8

# paragraph paths that repeat a whole roman-numeral run, "(i)(ii)(iii)(iv)(v)(vi)(4)...": a parsing defect in the source
# data (256 rows in 21 CFR 1114.7, found 2026-10-21). Such a row is never added: its citation would not match its text.
_MALFORMED_PATH_RE = re.compile(r"^\(i\)\(ii\)\(iii\)")

STATE_COVERED = "covered_in_base"
STATE_FILLED = "filled"
STATE_UNSUPPORTED = "unsupported_after_search"
STATE_NOT_SEARCHED = "not_searched"


@dataclass
class Candidate:
    result: RetrievalResult
    legs: dict[str, int] = field(default_factory=dict)     # leg -> 1-based rank in that leg
    tier: str = TIER_DISCOVERY

    @property
    def key(self) -> str:
        return self.result.key


@dataclass
class AdvancedRetrieval:
    db: Any
    flags: dict[str, bool] = field(default_factory=dict)
    lexical: Any = None                                       # LexicalRetriever for targeted searches
    semantic_loader: Callable[[], Any] | None = None
    _semantic: Any = None

    @classmethod
    def from_flags(cls, db, flags: dict[str, bool]) -> "AdvancedRetrieval":
        from regulus.retrieval import LexicalRetriever

        def load():
            from regulus.retrieval.semantic.loaders import load_semantic_retriever
            return load_semantic_retriever(offline=True, semantic_corpus="semantic_expanded_v1")

        known = {k: bool(flags.get(k) or flags.get(f"adv.{k}")) for k in FLAGS}
        return cls(db, known, LexicalRetriever(db), load)

    def on(self, flag: str) -> bool:
        return bool(self.flags.get(flag))

    # ------------------------------------------------------------------ main

    def extend(self, selection, registry: EvidenceRegistry, question: str, policy, *, block_chars: Callable,
               clean: Callable, truncate: Callable) -> tuple[Any, dict[str, Any]]:
        """The base selection plus, for uncovered plan elements, appended evidence; and the trace."""
        from regulus.rag.selection import Selection, SelectedEvidence

        t0 = time.perf_counter()
        plan = build_regulatory_plan(question)
        trace: dict[str, Any] = {"flags": {k: v for k, v in self.flags.items() if v}, "plan": plan.to_dict(),
                                 "elements": [], "added": [], "legs": {}, "skipped": None}
        if plan.non_fda:
            trace["skipped"] = "the question is about another agency's rules"
        elif registry.plan.requirements:
            trace["skipped"] = "the question names a provision"
        elif not plan.elements:
            trace["skipped"] = "no element to check"
        if trace["skipped"]:
            trace["ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return replace(selection, diagnostics={**selection.diagnostics, "advanced": trace}), trace

        selected = list(selection.selected)
        uncovered = [e for e in plan.elements if not self._covering(e, [s.evidence.result for s in selected])]
        for e in plan.elements:
            if e not in uncovered:
                trace["elements"].append({"id": e.id, "state": STATE_COVERED})

        pool = self._candidates(plan, uncovered, selected, registry, trace)
        order = self._order(pool)
        trace["legs"]["order"] = [{"key": c.key, "legs": c.legs} for c in order[:12]]

        added: list[tuple[Candidate, str]] = []
        if self.on("gap_fill"):
            have = {s.evidence.key for s in selected}
            spent = 0
            # a lead-in is completed with ALL of its subparagraphs or not at all: measured on the answer gate, a list cut
            # to its first three items was answered as if complete (20 Oct, 820.35(a), 50.25(a))
            for group in self._completion_groups(pool):
                fresh = [c for c in group if c.key not in have]
                size = sum(len(c.result.text or "") for c in fresh)
                if fresh and len(added) + len(fresh) <= GAP_MAX_SOURCES and spent + size <= GAP_RESERVE_CHARS:
                    for c in fresh:
                        added.append((c, "completion")); have.add(c.key)
                    spent += size
                elif fresh:
                    trace["added"].append({"key": fresh[0].result.metadata.get("parent"), "for": "completion", "kept": False,
                                           "why": f"{len(fresh)} subparagraphs do not all fit the reserve"})
            named_absent = [e for e in uncovered if e.kind == "named_thing" and not any(self._covering(e, [c.result]) for c in pool)]
            for e in uncovered:
                if named_absent:
                    # the specific thing the question names is not in the corpus: evidence for its other words is
                    # about something else (a negative control asking about a guidance document that does not exist)
                    trace["elements"].append({"id": e.id, "state": STATE_UNSUPPORTED,
                                              "why": f"named thing not found: {named_absent[0].text}"})
                    continue
                best = next((c for c in order if c.key not in have and self._covering(e, [c.result])), None)
                if best is None:
                    trace["elements"].append({"id": e.id, "state": STATE_UNSUPPORTED if pool else STATE_NOT_SEARCHED})
                    continue
                if len(added) >= GAP_MAX_SOURCES or spent + len(best.result.text or "") > GAP_RESERVE_CHARS:
                    trace["elements"].append({"id": e.id, "state": STATE_NOT_SEARCHED, "why": "reserve exhausted"})
                    continue
                added.append((best, e.id)); have.add(best.key); spent += len(best.result.text or "")
                trace["elements"].append({"id": e.id, "state": STATE_FILLED, "by": best.key, "legs": best.legs})
        else:   # gap filling off: say what a fill would have had to work with, add nothing
            for e in uncovered:
                found = [c.key for c in order if self._covering(e, [c.result])]
                trace["elements"].append({"id": e.id, "state": "candidate_found" if found else STATE_UNSUPPORTED,
                                          "candidates": found[:3]})

        used = selection.total_chars
        for n, (c, why) in enumerate(added, start=1):
            evidence = Evidence(f"a{n}", c.result, c.tier)
            text, truncated = truncate(clean(c.result.text), policy.max_chars_per_result)
            index = len(selected) + 1
            chars = block_chars(evidence, text, index, truncated)
            if len(selected) >= policy.hard_max_results or used + 2 + chars > policy.hard_max_total_chars:
                trace["added"].append({"key": c.key, "for": why, "kept": False, "why": "hard ceiling"})
                continue
            used += 2 + chars
            selected.append(SelectedEvidence(index, evidence, text, truncated, False, f"advanced_{'completion' if why == 'completion' else 'gap'}", chars))
            trace["added"].append({"key": c.key, "citation": c.result.citation.label, "for": why, "legs": c.legs, "chars": chars, "kept": True})
        trace["ms"] = round((time.perf_counter() - t0) * 1000, 2)
        if not any(a["kept"] for a in trace["added"]):
            return replace(selection, diagnostics={**selection.diagnostics, "advanced": trace}), trace
        return (Selection(tuple(selected), selection.dropped, selection.policy, used, {**selection.diagnostics, "advanced": trace}),
                trace)

    # ------------------------------------------------------------- coverage

    @staticmethod
    def _covering(element: PlanElement, results: list[RetrievalResult]) -> bool:
        """Binding text only: a guidance chunk on the topic does not establish what the regulation requires, so it
        never counts as covering an element (and never stands in for the CFR provision that would)."""
        for r in results:
            if r.corpus != "ecfr":
                continue
            md = r.metadata or {}
            context = " ".join(str(x) for x in (r.heading, md.get("part_title"), r.citation.label if r.citation else "") if x)
            if element.covered_by(r.text or "", context):
                return True
        return False

    # ----------------------------------------------------------- candidates

    def _candidates(self, plan: RegulatoryPlan, uncovered: list[PlanElement], selected, registry: EvidenceRegistry,
                    trace: dict[str, Any]) -> list[Candidate]:
        pool: dict[str, Candidate] = {}
        chosen = {s.evidence.key for s in selected}

        def add(leg: str, results: list[RetrievalResult], tier: str | None = None):
            n = 0
            for r in results:
                if r.key in chosen or r.corpus != "ecfr" or (r.citation and r.citation.label and not r.citation.label.startswith("21 CFR")):
                    continue
                if _MALFORMED_PATH_RE.match((r.metadata or {}).get("paragraph_path") or ""):
                    continue   # a source-data defect (256 rows, 21 CFR 1114.7): its citation would mislabel the text
                n += 1
                c = pool.setdefault(r.key, Candidate(r, {}, (r.metadata or {}).get("parent_tier") or tier or TIER_DISCOVERY))
                c.legs.setdefault(leg, n)
                if n >= LEG_CANDIDATES:
                    break
            trace["legs"][leg] = n

        # the retriever's own candidates that selection did not keep
        if uncovered:
            add("lexical", [e.result for e in registry.evidence if e.key not in chosen])
        if self.on("structure"):
            # only a lead-in that addresses something the question asks: completing an off-topic one adds noise
            leadins = [s for s in selected if (s.evidence.result.text or "").rstrip().endswith(":")
                       and any(self._covering(e, [s.evidence.result]) for e in plan.elements)]
            add("structure", self._children(leadins))
        if uncovered and self.on("xref"):
            add("xref", self._cited([s.evidence.result for s in selected]))
        # a CFR part the question's own candidates come from: semantic and targeted hits outside it drifted to another
        # domain when measured (a tobacco question pulling IND and NDA sections)
        parts = {(s.evidence.result.metadata or {}).get("part") for s in selected if s.evidence.result.corpus == "ecfr"}
        parts |= {(e.result.metadata or {}).get("part") for e in [e for e in registry.evidence if e.result.corpus == "ecfr"][:CORROBORATING]}
        if uncovered and self.on("semantic"):
            for e in uncovered:
                add(f"semantic:{e.id}", [r for r in self._semantic_hits(e) if (r.metadata or {}).get("part") in parts])
        if uncovered and self.on("iterate"):
            for e in uncovered[:ITERATE_MAX_SEARCHES]:
                hits = self._targeted(e, plan)
                add(f"iterate:{e.id}", [r for r in hits if (r.metadata or {}).get("part") in parts])
        return list(pool.values())

    def _order(self, pool: list[Candidate]) -> list[Candidate]:
        if self.on("fusion"):
            score = lambda c: sum(1.0 / (RRF_K + rank) for rank in c.legs.values())
            return sorted(pool, key=lambda c: (-score(c), c.key))
        leg_order = ["lexical", "structure", "xref"]
        def first(c):
            ranks = [(leg_order.index(l.split(":")[0]) if l.split(":")[0] in leg_order else len(leg_order), r) for l, r in c.legs.items()]
            return min(ranks)
        return sorted(pool, key=lambda c: (first(c), c.key))

    def _completion_groups(self, pool: list[Candidate]) -> list[list[Candidate]]:
        """The structure leg's subparagraphs, one group per lead-in, in document order."""
        if not self.on("structure"):
            return []
        groups: dict[str, list[Candidate]] = {}
        for c in pool:
            if "structure" in c.legs:
                groups.setdefault((c.result.metadata or {}).get("parent") or c.key, []).append(c)
        return [sorted(g, key=lambda c: (c.result.metadata or {}).get("ordinal") or 0) for g in groups.values()]

    def _children(self, leadins) -> list[RetrievalResult]:
        from regulus.retrieval.lexical import LexicalRetriever
        out = []
        for s in leadins:
            md = s.evidence.result.metadata or {}
            section, para = md.get("section"), md.get("paragraph_path") or ""
            if not section:
                continue
            rows = self.db.query(sql.ECFR_EXACT_SECTION, {"section_number": section, "paragraph": para, "paragraph_prefix": f"{para}(%" if para else "%",
                                                          "limit": CHILD_LIMIT + 1, "part": None, "section": None, "subchapter": None})
            for row in rows:
                if (row.get("paragraph_path") or "") != para:
                    out.append(LexicalRetriever._ecfr_result(row, METHOD_EXACT_CFR, 1.0, {
                        "leg": "advanced_structure", "parent": s.evidence.result.citation.label, "parent_tier": s.evidence.tier}))
        return out[:CHILD_LIMIT]

    def _cited(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        from regulus.retrieval.lexical import LexicalRetriever
        seeds = [r for r in results if r.corpus == "ecfr" and (r.metadata or {}).get("section")][:4]
        if not seeds:
            return []
        rows = self.db.query(sql.ECFR_CROSS_REFERENCED, {"section_number": [r.metadata["section"] for r in seeds],
                                                         "paragraph": [r.metadata.get("paragraph_path") or "" for r in seeds],
                                                         "limit": 40, "part": None, "section": None, "subchapter": None})
        return [LexicalRetriever._ecfr_result(row, METHOD_CROSS_REFERENCE, 0.5, {"leg": "advanced_xref", "xref_text": row.get("xref_text")})
                for row in rows]

    def _semantic_hits(self, element: PlanElement) -> list[RetrievalResult]:
        if self._semantic is None and self.semantic_loader is not None:
            try:
                self._semantic = self.semantic_loader()
            except Exception:   # an unavailable index must not break answering
                self.semantic_loader = None
                return []
        if self._semantic is None:
            return []
        query = element.text if not element.subject_keys else f"{element.text} {' '.join(element.subject_keys)}"
        return [r for r in self._semantic.run(query, top_k=LEG_CANDIDATES).results if r.relevance_score >= SEMANTIC_FLOOR]

    def _targeted(self, element: PlanElement, plan: RegulatoryPlan) -> list[RetrievalResult]:
        from regulus.planning import plan_query
        words = [element.text] + ([" ".join(element.subject_keys)] if element.subject_keys else [])
        found = self.lexical.run_plan(plan_query(" ".join(words) + "?"), top_k=LEG_CANDIDATES).registry.evidence
        return [e.result for e in found if e.result.corpus == "ecfr"]
