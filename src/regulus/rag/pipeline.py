"""RagPipeline: question -> Retriever -> context -> Generator -> answer + citations.

Citations never come from the model. They are the authoritative Citation
objects of the retrieval results that were placed in the context; the model
may refer to them as [n]. Sources with the same citation label (several
chunks of one guidance document) are reported once with all their indices.
"""

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from regulus.inference.types import GenerationResult
from regulus.planning import QueryPlan, plan_query
from regulus.planning.intent import SCOPE_MIXED, SCOPE_OUT, TYPE_CITATION, QuestionAnalysis, analyze_question
from regulus.planning.shape import MODE_COMPARISON, MODE_ENUMERATION, MODE_FOCUSED, AnswerShape, analyze_shape
from regulus.rag import answerability as gate
from regulus.rag.answer_quality import mixed_scope_note, normalize_answer, out_of_scope_answer, quality_flags
from regulus.rag.context import ContextBundle, ContextPolicy, build_context, render_selection
from regulus.rag.citations import ROLE_CONTEXT, RagCitation, build_answer_citations, citation_support
from regulus.rag.coverage import STATE_INCOMPLETE, CoverageReport, check_coverage
from regulus.rag.generation import (
    UNVALIDATED_GENERAL,
    UNVALIDATED_PREFIX,
    GenerationBudget,
    GenerationPackage,
    build_grounded_messages,
    build_package,
    extractive_answer,
    extractive_items,
)
from regulus.rag.fallback import FB_UNVALIDATED, blocked_answer, quoting_allowed, unvalidated_answer
from regulus.rag.selection import Selection, is_complete_sentence, required_only, select_evidence
from regulus.rag.shape_validation import ENUMERATION_INCOMPLETE, MATERIAL_GROUP_UNCOVERED
from regulus.rag.validation import (
    CITATION_MISMATCH,
    PROVISION_CITATION_MISMATCH,
    REFUSAL_WITH_EVIDENCE,
    STATUS_CITATION_INVALID,
    STATUS_DEGENERATE,
    STATUS_EMPTY,
    STATUS_EVIDENCE_MISMATCHED,
    STATUS_UNSUPPORTED,
    ValidationReport,
    attach_trailing_markers,
    strip_invalid_citations,
    validate_answer,
)
if TYPE_CHECKING:  # annotation only; importing it would load torch
    from regulus.rag.generator import Generator
from regulus.rag.prompt import NO_CONTEXT_ANSWER, build_messages, coverage_note, incomplete_coverage_answer, unresolved_provisions_statement
from regulus.retrieval.base import Filters
from regulus.retrieval.evidence import REL_CHILD, TIER_EXACT, TIER_STRUCTURAL, Evidence, EvidenceRegistry
from regulus.retrieval.lexical import LexicalRetriever, SearchResponse
from regulus.retrieval.models import METHOD_TRIGRAM, RetrievalResult

_CITE_RE = re.compile(r"\[(\d{1,2})\]")
# Stage 5: final validation states that mean the shown text is not grounded (a repair that failed)
_UNGROUNDED = (STATUS_EMPTY, STATUS_DEGENERATE, STATUS_UNSUPPORTED, STATUS_EVIDENCE_MISMATCHED)
# Stage 5: blocked answers keep the coverage_action earlier stages recorded for the same situation
_BLOCK_ACTIONS = {"out_of_scope": "refuse_out_of_scope", "provision_not_found": "refuse_unsupported", "no_evidence": None}


@dataclass(frozen=True)
class RagConfig:
    top_k: int = 8
    corpus: str | None = None
    # Trigram-only hits at the pg_trgm floor (similarity 0.3 -> score 1.5) are
    # mostly headings sharing a common word. Provisional cut-off, not tuned on
    # the benchmark: documented in docs/lexical_rag.md.
    min_trigram_similarity: float = 0.4
    # "refuse": deterministic no-context answer without calling the model (default,
    # conservative). "model": send the empty-sources prompt to the model.
    no_context_behavior: str = "refuse"
    # Stage 9: a retriever may mark results as contextual_only when the query
    # named an identifier (CFR section/part, docket) that has no live record.
    # Such passages are related material, not evidence the identifier exists;
    # by default they are kept out of the grounding context so the answer
    # falls back to the deterministic not-found response.
    exclude_contextual_only: bool = True
    context: ContextPolicy = field(default_factory=ContextPolicy)
    # Stage 3: what to do when explicit requirements lack exact evidence.
    # "partial": answer from the supported provisions only and state which were
    # not found; when none is supported, answer deterministically without the
    # model. "model": send whatever was selected to the model (legacy).
    incomplete_behavior: str = "partial"
    # Stage 4: per-question token budget and what to do with a generated answer
    # that fails deterministic validation. "repair": replace or complete it from
    # the exact sources; "annotate": keep it and report; "off": skip validation.
    generation_budget: GenerationBudget = field(default_factory=GenerationBudget)
    validation_behavior: str = "repair"
    # Stage 12: "adaptive" derives an AnswerShape from the question and gives
    # the model the evidence organised for it (docs/adaptive_answer_shape.md);
    # "off" restores the previous prompt and selection, for measurement.
    # "structured" (answer-quality Stage 3, docs/answer_quality.md) adds question
    # analysis, answer profiles, deterministic scope handling, answer
    # normalisation and quality flags on top of "adaptive".
    answer_shape: str = "adaptive"
    # Stage 5 (docs/answerability_gate_stage5.md): "gate" decides answerability before
    # generation, blocks unanswerable questions without calling the model and uses the
    # safe fallback builder; "off" restores the Stage 4 behaviour, for measurement.
    answerability: str = "gate"
    # Stage 6 (docs/generation_quality_stage6.md): "incomplete_only" gives the model only the
    # protected evidence (exact + structural) when every requested provision has exact evidence,
    # and keeps optional supporting/discovery sources only when something requested is missing
    # or no provision was requested; "always" restores the Stage 5 context, for measurement.
    optional_context: str = "incomplete_only"

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.no_context_behavior not in ("refuse", "model"):
            raise ValueError("no_context_behavior must be 'refuse' or 'model'")
        if self.incomplete_behavior not in ("partial", "model"):
            raise ValueError("incomplete_behavior must be 'partial' or 'model'")
        if self.validation_behavior not in ("repair", "annotate", "off"):
            raise ValueError("validation_behavior must be 'repair', 'annotate' or 'off'")
        if self.answer_shape not in ("adaptive", "structured", "off"):
            raise ValueError("answer_shape must be 'adaptive', 'structured' or 'off'")
        if self.answerability not in ("gate", "off"):
            raise ValueError("answerability must be 'gate' or 'off'")
        if self.optional_context not in ("incomplete_only", "always"):
            raise ValueError("optional_context must be 'incomplete_only' or 'always'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "retriever": "LexicalRetriever",
            "top_k": self.top_k,
            "corpus": self.corpus or "all",
            "min_trigram_similarity": self.min_trigram_similarity,
            "no_context_behavior": self.no_context_behavior,
            "exclude_contextual_only": self.exclude_contextual_only,
            "incomplete_behavior": self.incomplete_behavior,
            "generation_budget": self.generation_budget.to_dict(),
            "validation_behavior": self.validation_behavior,
            "answer_shape": self.answer_shape,
            "answerability": self.answerability,
            "optional_context": self.optional_context,
            "context": self.context.to_dict(),
        }


@dataclass
class RagAnswer:
    question: str
    answer: str
    citations: list[RagCitation]
    retrieved_results: list[RetrievalResult]
    context: ContextBundle
    no_context: bool
    model_called: bool
    timings_ms: dict[str, float]
    input_tokens: int | None
    output_tokens: int | None
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: EvidenceRegistry | None = None  # Stage 2 registry (None on the legacy path)
    coverage: CoverageReport | None = None    # Stage 3 coverage (None on the legacy path)
    selection: Selection | None = None        # Stage 3 selection (None on the legacy path)
    package: GenerationPackage | None = None  # Stage 4 generation contract (None on the legacy path)
    validation: ValidationReport | None = None  # Stage 4 final validation (None when not generated/validated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "retrieved": [
                {"rank": i, "corpus": r.corpus, "citation": r.citation.label, "url": r.source_url, "score": round(r.relevance_score, 4), "method": r.retrieval_method, "key": r.key}
                for i, r in enumerate(self.retrieved_results, start=1)
            ],
            "context": self.context.to_dict(),
            "no_context": self.no_context,
            "model_called": self.model_called,
            "timings_ms": self.timings_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "metadata": self.metadata,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Compact per-question record for the benchmark (retrieval vs generation)."""
        d = self.to_dict()
        out = {k: d[k] for k in ("retrieved", "context", "citations", "no_context", "model_called", "timings_ms")}
        out["retrieval"] = dict(self.metadata.get("retrieval", {}))
        out["grounding"] = self.metadata.get("grounding")
        # Stage 3 keys are added only when present so legacy runs keep their shape
        for key in ("coverage", "coverage_action", "generation", "validation", "citation_support", "answer_shape",
                    "question_analysis", "quality_flags"):
            if self.metadata.get(key) is not None:
                out[key] = self.metadata[key]
        if self.package is not None:  # Stage 5 gate record (the legacy path keeps its shape)
            for key in ("answerability", "generation_called", "generation_blocked", "block_reason", "fallback_type", "fallback_reason"):
                out[key] = self.metadata.get(key)
        return out


@dataclass
class RagGenerationResult(GenerationResult):
    """GenerationResult plus RAG diagnostics, so the existing evaluation runner
    can store retrieval information without changing its interface."""

    diagnostics: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)


class RagPipeline:
    def __init__(self, retriever: LexicalRetriever, generator: Generator, config: RagConfig | None = None, grounding=None) -> None:
        """`grounding` is an optional Stage 13 GroundingGate. It is None by
        default, so the Stage 6/7 pipeline is unchanged. When supplied it runs
        after retrieval and context construction and can replace the generated
        answer with a deterministic refusal; retrieval itself is never altered,
        which keeps runs comparable across stages."""
        self.retriever = retriever
        self.generator = generator
        self.config = config or RagConfig()
        self.grounding = grounding

    # -- steps ---------------------------------------------------------------

    def retrieve(self, question: str, plan: QueryPlan | None = None) -> tuple[SearchResponse, EvidenceRegistry | None]:
        """Stage 2: plan-driven retrieval when the retriever supports it.

        The plan is built once per question (here if the caller did not pass
        one) and handed to `run_plan`, so retrieval never re-parses the
        question. Retrievers without `run_plan` (hybrid, semantic, test fakes)
        keep the query-level path and return no registry.
        """
        run_plan = getattr(self.retriever, "run_plan", None)
        if run_plan is None:
            return self.retriever.run(question, corpus=self.config.corpus, top_k=self.config.top_k, filters=Filters()), None
        plan = plan if plan is not None else plan_query(question)
        out = run_plan(plan, corpus=self.config.corpus, top_k=self.config.top_k, filters=Filters())
        return out.response, out.registry

    def is_useful(self, r: RetrievalResult) -> bool:
        """Usefulness rule for optional evidence: drop trigram-only hits below the
        cut-off and (by default) contextual-only passages."""
        if r.retrieval_method == METHOD_TRIGRAM and float(r.metadata.get("similarity", 0.0)) < self.config.min_trigram_similarity:
            return False
        if self.config.exclude_contextual_only and r.metadata.get("contextual_only"):
            return False
        return True

    def select_useful(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Legacy path: keep the retriever's own ordering, apply is_useful()."""
        return [r for r in results if self.is_useful(r)]

    def shape_for(self, plan: QueryPlan) -> AnswerShape | None:
        """Stage 12: the answer shape, or None when the setting is off."""
        return analyze_shape(plan) if self.config.answer_shape in ("adaptive", "structured") else None

    def analysis_for(self, plan: QueryPlan) -> QuestionAnalysis | None:
        """Answer-quality Stage 3: the question analysis, only in "structured" mode."""
        return analyze_question(plan) if self.config.answer_shape == "structured" else None

    def question_view(self, plan: QueryPlan) -> tuple[AnswerShape | None, QuestionAnalysis | None]:
        """The answer shape and question analysis the pipeline acts on: the ONE place
        they are decided, so anything that rebuilds a prompt (evaluation) rebuilds it exactly."""
        shape, analysis = self.shape_for(plan), self.analysis_for(plan)
        if analysis is not None and shape is not None and analysis.question_type == TYPE_CITATION and shape.mode == MODE_ENUMERATION:
            # "Which provision ...?" asks for one provision; naming a second part in the question
            # ("... refers to part 806") must not turn it into an exhaustive list of every paragraph
            shape = replace(shape, mode=MODE_FOCUSED, exhaustive=False, signals=shape.signals + ("citation_lookup_not_enumeration",),
                            rationale="a citation lookup: name the provision that answers, not every provision")
        return shape, analysis

    @staticmethod
    def is_subordinate(evidence: Evidence) -> bool:
        """A child paragraph of a requested provision: part of what was asked for."""
        return evidence.tier == TIER_STRUCTURAL and REL_CHILD in evidence.relations.values()

    def select(self, registry: EvidenceRegistry, shape: AnswerShape | None = None) -> Selection:
        """Stage 3 selection; with a Stage 12 shape, children of requested
        provisions are kept like required evidence instead of competing for the
        soft budget. Stage 5 calls this too, so it measures what the pipeline uses."""
        material = self.is_subordinate if shape is not None else None
        return select_evidence(registry, self.config.context, optional_filter=self.is_useful, material=material)

    def build_bundle(self, response: SearchResponse, registry: EvidenceRegistry | None, shape: AnswerShape | None = None) -> tuple[ContextBundle, CoverageReport | None, Selection | None]:
        """Stage 3: coverage -> selection -> rendering when a registry exists;
        the legacy filter + build_context otherwise."""
        if registry is None:
            return build_context(self.select_useful(response.results), self.config.context, notes=response.notes), None, None
        coverage = check_coverage(registry)
        selection = self.select(registry, shape)
        if (self.config.optional_context == "incomplete_only" and coverage.explicit and coverage.complete
                and not (shape is not None and shape.mode == MODE_COMPARISON)
                and all(is_complete_sentence(s.text) for s in selection.selected if s.protected and s.evidence.tier == TIER_EXACT)):
            # Stage 6: the exact evidence is all the model needs, when it is complete text on its own.
            # Kept in full (the Stage 5 context): a comparison, which contrasts each side's applicability and
            # conditions carried by the parent/child paragraphs (AS-05 overstated a scope without them), and a
            # requested provision whose text is a lead-in or a chained fragment, which the model misreads
            # without its parent and siblings (S5-011, S5-032, S5-101). docs/generation_quality_stage6.md
            selection = required_only(selection)
        notes = list(response.notes)
        if coverage.state == STATE_INCOMPLETE:
            notes.append(coverage_note(coverage.missing_labels))
        return render_selection(selection, notes=notes), coverage, selection

    def build_citations(self, bundle: ContextBundle, answer: str) -> list[RagCitation]:
        mentioned = {int(m) for m in _CITE_RE.findall(answer)}
        grouped: dict[str, list] = {}
        for s in bundle.sources:
            grouped.setdefault(s.result.citation.label, []).append(s)
        out = []
        for label, group in grouped.items():
            first = group[0]
            indices = tuple(s.index for s in group)
            out.append(
                RagCitation(
                    index=first.index,
                    indices=indices,
                    label=label,
                    corpus=first.result.corpus,
                    url=first.result.source_url,
                    cited_in_answer=any(i in mentioned for i in indices),
                    citation=first.result.citation.to_dict(),
                    tier=first.tier,
                    requirement_ids=first.requirement_ids,
                    role=ROLE_CONTEXT,
                )
            )
        return sorted(out, key=lambda c: c.index)

    # -- Stage 4: generation contract, validation, repair --------------------

    def _generate(self, messages, max_new_tokens: int | None, on_text=None):
        """Call the generator with the per-question budget when it accepts one,
        and with the streaming text callback when there is one and it accepts it."""
        fn = self.generator.generate
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        kwargs = {}
        if "max_new_tokens" in params and max_new_tokens:
            kwargs["max_new_tokens"] = max_new_tokens
        if on_text is not None and "on_text" in params:
            kwargs["on_text"] = on_text
        return fn(messages, **kwargs)

    def repair_answer(self, text: str, package: GenerationPackage, report: ValidationReport, *, quote: bool = True,
                      unquotable: frozenset[str] = frozenset(), sources=None) -> tuple[str, str | None]:
        """Deterministic repair from the exact sources; never invents content.

        empty / degenerate / unsupported / refusal with evidence -> the answer is
        replaced by the verbatim exact text of the requested provisions (or a
        safe message when there are none); invalid markers are removed;
        requested provisions the model left out are appended verbatim; a
        truncated answer is marked as such.

        Stage 5 (the pipeline passes these when the answerability gate is on):
        `quote` False -> a replaced answer is withheld with a safe message instead of
        quoting sources that were not shown to answer the question; `unquotable`
        requirement ids (part-level requests) are never appended verbatim, because
        their first matching passage is not what was asked; `sources` lets the safe
        message name the sources consulted.
        """
        codes = report.codes()
        replace_all = report.status in (STATUS_EMPTY, STATUS_DEGENERATE, STATUS_UNSUPPORTED) or REFUSAL_WITH_EVIDENCE in codes
        if replace_all:
            if quote and package.satisfied_ids:
                return f"{UNVALIDATED_PREFIX}\n{extractive_answer(package)}", "extractive_replacement"
            if sources is not None:
                return unvalidated_answer(package, sources, quote=False)[0], FB_UNVALIDATED
            return UNVALIDATED_GENERAL, "safe_message"
        repairs: list[str] = []
        if report.status == STATUS_CITATION_INVALID:
            text = strip_invalid_citations(text, report.invalid_citations)
            repairs.append("invalid_citations_removed")
        # a statement about a requested provision that cites unrelated sources is
        # removed and the provision's verbatim exact text takes its place
        mismatched = [p for p in report.problems if p.code in (CITATION_MISMATCH, PROVISION_CITATION_MISMATCH) and p.sentence]
        if mismatched:
            normalized = attach_trailing_markers(text)
            for prob in mismatched:
                normalized = normalized.replace(prob.sentence, "")
            text = re.sub(r"[ \t]{2,}", " ", normalized).strip()
            affected = tuple(dict.fromkeys(p.requirement_id for p in mismatched if p.requirement_id)) or tuple(package.satisfied_ids)
            affected = tuple(r for r in affected if r not in unquotable)
            if affected:
                text = (text.rstrip() + "\n" if text.strip() else "") + extractive_answer(package, affected)
            repairs.append("mismatched_statements_replaced")
        missing = tuple(r for r in report.unaddressed if not any(p.requirement_id == r for p in mismatched) and r not in unquotable)
        if missing:
            text = (text.rstrip() + "\n" if text.strip() else "") + extractive_answer(package, missing)
            repairs.append("appended_missing_provisions")
        # Stage 12: items of an explicit enumeration, or whole requirement groups of a
        # synthesis, that the answer left out - appended verbatim from their sources
        items = tuple(dict.fromkeys(p.citation for p in report.problems if p.code == ENUMERATION_INCOMPLETE and p.citation is not None))
        plan = package.answer_plan
        for p in report.problems:
            if p.code == MATERIAL_GROUP_UNCOVERED and plan is not None and (g := plan.group_of(p.citation)) is not None:
                items += tuple(i for i in g.members if i not in items)
        if items:
            text = (text.rstrip() + "\n" if text.strip() else "") + extractive_items(package, items)
            repairs.append("appended_missing_items")
        if report.truncated:
            # Never present a severed answer as a finished one. Any requested
            # provision the cut removed has already been appended verbatim
            # above, so this marks what is left: prose that stopped mid-thought.
            text = text.rstrip() + (
                "\n(Incomplete: generation stopped at the token limit before this answer finished, "
                "so wording after this point is missing.)"
            )
            repairs.append("truncation_noted")
        return text, "+".join(repairs) if repairs else None

    def repair_with_fallback(self, text: str, package: GenerationPackage, report: ValidationReport, gen, *, question: str,
                             plan: QueryPlan, shape: AnswerShape | None, analysis: QuestionAnalysis | None, sources) -> dict[str, Any]:
        """Repair a generated answer that failed validation, then (Stage 5, answerability="gate") never
        show a result that is still ungrounded: it is replaced by the safe fallback builder. The one
        implementation used by `answer()` and by the evaluation harness.

        Returns text, repair, repair_output (the repair's own text), final (validation report),
        fallback_type and fallback_reason."""
        gate_on = self.config.answerability == "gate"
        quote = quoting_allowed(question, plan, shape, analysis, package) if gate_on else True
        kwargs = ({"quote": quote, "unquotable": frozenset(r.id for r in plan.requirements if r.reference.section is None),
                   "sources": sources} if gate_on else {})
        text, repair = self.repair_answer(text, package, report, **kwargs)
        repair_output = text if repair is not None else None
        final = validate_answer(text, package, gen) if repair is not None else report
        fallback_type = fallback_reason = None
        if repair == FB_UNVALIDATED:
            fallback_type, fallback_reason = FB_UNVALIDATED, f"the generated answer failed validation: {report.status}"
        elif gate_on and (final.status in _UNGROUNDED or REFUSAL_WITH_EVIDENCE in final.codes()):
            failed_status = final.status
            text, fallback_type = unvalidated_answer(package, sources, quote=quote)
            fallback_reason = f"the repaired answer still failed validation: {failed_status}"
            repair = (repair + "+" if repair else "") + "failed_repair_fallback"
            final = validate_answer(text, package, gen)
        return {"text": text, "repair": repair, "repair_output": repair_output, "final": final,
                "fallback_type": fallback_type, "fallback_reason": fallback_reason}

    # -- main entry ----------------------------------------------------------

    def answer(self, question: str, on_event=None) -> RagAnswer:
        """Answer a question. `on_event(kind, data)`, when given, is told about
        progress as it happens - "context" (the sources selected), "generation_started",
        "delta" (draft text of the one generation, as produced), "generation_finished" -
        so a caller can stream. It never changes the answer: validation and repair
        still run on the complete text, and the returned RagAnswer is the final
        result. An exception raised by `on_event` aborts the call (used to cancel
        generation when a streaming client disconnects)."""
        if not question or not question.strip():
            raise ValueError("question must not be empty")
        emit = on_event or (lambda kind, data: None)
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        plan = plan_query(question)  # Stage 1: the one and only parse of the question
        # Stage 12 shape + Stage 3 question analysis (None unless "structured"), decided in one place
        shape, analysis = self.question_view(plan)
        timings["plan_ms"] = round((time.perf_counter() - t0) * 1000, 2)  # part of retrieval_ms
        response, registry = self.retrieve(question, plan)
        timings["retrieval_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        t1 = time.perf_counter()
        bundle, coverage, selection = self.build_bundle(response, registry, shape)
        timings["context_ms"] = round((time.perf_counter() - t1) * 1000, 2)
        emit("context", {"no_context": bundle.is_empty, "sources": [
            {"index": s.index, "citation": s.result.citation.label, "corpus": s.result.corpus, "url": s.result.source_url,
             "tier": s.tier} for s in bundle.sources]})

        no_context = bundle.is_empty
        model_called = False
        input_tokens = output_tokens = None

        # Stage 13 grounding gate: decided from the verified database and from
        # structural identifier comparison, never from similarity.
        grounding_decision = None
        if self.grounding is not None:
            verification, pre = self.grounding.check_identifier(question)
            grounding_decision = pre
            if not pre.refused:
                post = self.grounding.check_context(verification, [s.result for s in bundle.sources])
                if post.checked:
                    grounding_decision = post
        # Stage 3: explicit requirements without exact evidence. With nothing
        # supported the answer is deterministic (the model is not asked to
        # describe a provision it was not given); with some supported the model
        # answers from those and the unresolved ones are stated afterwards.
        t_pkg = time.perf_counter()
        package = (build_package(plan, coverage, selection, notes=bundle.notes, budget=self.config.generation_budget, answer_shape=shape,
                                 question_analysis=analysis)
                   if coverage is not None and selection is not None else None)
        normalization: dict[str, Any] | None = None
        # Failure observatory: the stages of the text, kept separately so that a
        # later step can never hide what an earlier one produced. None when no model call.
        raw_model_output: str | None = None
        repair_input: str | None = None
        repair_output: str | None = None
        timings["package_ms"] = round((time.perf_counter() - t_pkg) * 1000, 2)
        validation_initial: ValidationReport | None = None
        validation_final: ValidationReport | None = None
        repair: str | None = None
        generation_info: dict[str, Any] = {}
        partial = self.config.incomplete_behavior == "partial"
        incomplete = coverage is not None and coverage.state == STATE_INCOMPLETE
        unsupported = incomplete and partial and not coverage.satisfied_ids
        coverage_action = None
        # Stage 5 answerability gate: decided from the plan, the question analysis, coverage and the
        # selected evidence, before any prompt is built. Computed in both modes (so "off" runs record
        # what the gate would have decided); acted on only when answerability="gate".
        t_gate = time.perf_counter()
        gate_on = self.config.answerability == "gate"
        gate_analysis = analysis if analysis is not None else analyze_question(plan)
        decision = gate.decide(question, plan, gate_analysis, coverage=coverage, sources=bundle.sources, no_context=no_context)
        conditions = decision.blocking_conditions
        block = gate_on and decision.blocked and not (
            ("no_evidence" in conditions and self.config.no_context_behavior != "refuse")
            or ("requested_provision_not_found" in conditions and self.config.incomplete_behavior != "partial"))
        fallback_type: str | None = None
        fallback_reason: str | None = None
        timings["answerability_ms"] = round((time.perf_counter() - t_gate) * 1000, 2)
        if grounding_decision is not None and grounding_decision.refused:
            answer_text = grounding_decision.answer
            timings["generation_ms"] = 0.0
        elif block:
            # the model is not called: nothing it could say would be supported by this evidence
            answer_text, fallback_type = blocked_answer(decision, bundle.sources, bundle.notes,
                                                        coverage.missing_labels if coverage is not None else (),
                                                        plan=plan, package=package)
            fallback_reason = decision.reason
            coverage_action = _BLOCK_ACTIONS[fallback_type] if fallback_type in _BLOCK_ACTIONS else f"blocked_{decision.state.lower()}"
            timings["generation_ms"] = 0.0
        elif analysis is not None and analysis.scope_status == SCOPE_OUT:
            # Stage 3: a named non-U.S. framework; decided from the question, the model is not asked
            answer_text = out_of_scope_answer(analysis.scope_reason)
            coverage_action = "refuse_out_of_scope"
            timings["generation_ms"] = 0.0
        elif unsupported:
            answer_text = incomplete_coverage_answer(coverage.missing_labels)
            coverage_action = "refuse_unsupported"
            timings["generation_ms"] = 0.0
        elif no_context and self.config.no_context_behavior == "refuse":
            answer_text = NO_CONTEXT_ANSWER
            if bundle.notes:
                answer_text += " " + " ".join(bundle.notes)
            timings["generation_ms"] = 0.0
        else:
            t2 = time.perf_counter()
            messages = build_grounded_messages(package) if package is not None else build_messages(question, bundle.text)
            timings["prompt_ms"] = round((time.perf_counter() - t2) * 1000, 2)
            emit("generation_started", {"max_new_tokens": package.max_new_tokens if package is not None else None})
            on_text = (lambda text: emit("delta", {"text": text})) if on_event is not None else None
            t2 = time.perf_counter()
            gen = self._generate(messages, package.max_new_tokens if package is not None else None, on_text)
            timings["generation_ms"] = round((time.perf_counter() - t2) * 1000, 2)
            emit("generation_finished", {"generated_tokens": gen.generated_tokens, "finished": gen.finished})
            # Model-internal breakdown, when the generator measured it (None-safe for fakes)
            for key, attr in (("model_prepare_ms", "prepare_seconds"), ("model_first_token_ms", "first_token_seconds"),
                              ("model_detokenize_ms", "detokenize_seconds")):
                value = getattr(gen, attr, None)
                if value is not None:
                    timings[key] = round(value * 1000, 2)
            if getattr(gen, "first_token_seconds", None) is not None:
                timings["model_decode_ms"] = round((gen.seconds - gen.first_token_seconds) * 1000, 2)
            raw_model_output = gen.response  # exactly as generated, before any transformation
            answer_text = gen.response.strip()
            if analysis is not None:
                # Stage 3: presentation fixes before validation (markers onto their sentence, no echoed question)
                answer_text, normalization = normalize_answer(answer_text, question)
            model_called = True
            input_tokens, output_tokens = gen.prompt_tokens, gen.generated_tokens
            generation_info = {"generated_tokens": gen.generated_tokens, "finished": gen.finished, "prompt_tokens": gen.prompt_tokens}
            if getattr(gen, "first_token_seconds", None) is not None:
                generation_info["tokens_per_second"] = round(gen.tokens_per_second, 3)
                generation_info["decode_tokens_per_second"] = (round(gen.decode_tokens_per_second, 3)
                                                                if gen.decode_tokens_per_second is not None else None)
            if package is not None and self.config.validation_behavior != "off":
                t3 = time.perf_counter()
                validation_initial = validate_answer(answer_text, package, gen)
                validation_final = validation_initial
                if self.config.validation_behavior == "repair" and not validation_initial.ok:
                    repair_input = answer_text
                    r = self.repair_with_fallback(answer_text, package, validation_initial, gen, question=question, plan=plan,
                                                  shape=shape, analysis=gate_analysis, sources=bundle.sources)
                    answer_text, repair, repair_output, validation_final = r["text"], r["repair"], r["repair_output"], r["final"]
                    fallback_type, fallback_reason = r["fallback_type"], r["fallback_reason"]
                timings["validation_ms"] = round((time.perf_counter() - t3) * 1000, 2)
            if gate_on and decision.limitation and not (analysis is not None and analysis.scope_status == SCOPE_MIXED):
                # Stage 5 PARTIALLY_ANSWERABLE: say what the evidence does not establish (mixed scope in
                # "structured" mode already gets its own note below)
                answer_text = answer_text.rstrip() + "\n" + decision.limitation
            if incomplete and partial:
                # the extractive repair already states each missing provision as not found
                already = all(f"{label}: not found" in answer_text for label in coverage.missing_labels)
                if not already:
                    answer_text = (answer_text + " " if answer_text else "") + unresolved_provisions_statement(coverage.missing_labels)
                coverage_action = "answer_partial"
            elif coverage is not None:
                coverage_action = "answer"
            if analysis is not None and analysis.scope_status == SCOPE_MIXED and analysis.out_of_scope_part:
                answer_text = answer_text.rstrip() + "\n" + mixed_scope_note(analysis.out_of_scope_part)
        t_post = time.perf_counter()
        if package is not None and model_called:
            addressed = validation_final.addressed if validation_final is not None else ()
            citations = build_answer_citations(answer_text, package, addressed)
        elif package is not None and fallback_type is not None and _CITE_RE.search(answer_text):
            citations = build_answer_citations(answer_text, package)  # Stage 5: a fallback that quotes its provision cites it
        elif package is not None:
            citations = []  # deterministic answers cite nothing; the evidence is in the metadata
        else:
            citations = self.build_citations(bundle, answer_text)
        timings["citations_ms"] = round((time.perf_counter() - t_post) * 1000, 2)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        t_meta = time.perf_counter()
        out = RagAnswer(
            question=question,
            answer=answer_text,
            citations=citations,
            retrieved_results=list(response.results),
            context=bundle,
            evidence=registry,
            coverage=coverage,
            selection=selection,
            package=package,
            validation=validation_final,
            no_context=no_context,
            model_called=model_called,
            timings_ms=timings,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metadata={
                "grounding": grounding_decision.to_dict() if grounding_decision is not None else None,
                "query_type": response.query_type.value,
                # Stage 1 plan and Stage 2 evidence registry (None for retrievers
                # without run_plan). The registry is the per-requirement record
                # Stage 3 will consume; the context builder is unchanged.
                "plan": plan.to_dict(),
                # Stage 12 answer shape: None when answer_shape="off", and on the
                # legacy path, which has no package for a shape to organise
                "answer_shape": shape.to_dict() if shape is not None and package is not None else None,
                # answer-quality Stage 3 ("structured" only; None otherwise)
                "question_analysis": analysis.to_dict() if analysis is not None else None,
                # failure observatory: raw generation and the text repair received (repair output = the answer)
                "raw_model_output": raw_model_output,
                "repair_input": repair_input,
                "repair_output": repair_output,
                # Stage 5 answerability gate and safe fallback
                "answerability": {**decision.to_dict(), "acted_on": gate_on},
                "generation_called": model_called,
                "generation_blocked": block,
                "block_reason": decision.reason if block else None,
                "fallback_type": fallback_type,
                "fallback_reason": fallback_reason,
                "normalization": normalization,
                "quality_flags": (quality_flags(answer_text, package, analysis,
                                                validation_final.to_dict() if validation_final is not None else None,
                                                coverage_action=coverage_action, model_called=model_called, question=question)
                                  if analysis is not None else None),
                "evidence": registry.to_dict() if registry is not None else None,
                # Stage 3 coverage and selection (None on the legacy path)
                "coverage": coverage.to_dict() if coverage is not None else None,
                "selection": selection.to_dict() if selection is not None else None,
                "coverage_action": coverage_action,
                # Stage 4 generation contract and validation (None on the legacy path)
                "generation": ({**package.to_dict(), **generation_info, "prompt_chars": len(build_grounded_messages(package)[1]["content"])} if package is not None else None),
                "validation": ({"initial": validation_initial.to_dict(), "final": validation_final.to_dict(), "repair": repair} if validation_initial is not None else None),
                "citation_support": citation_support(answer_text, package) if package is not None and model_called else None,
                "contextual_only_excluded": sum(1 for r in response.results if r.metadata.get("contextual_only")) if self.config.exclude_contextual_only else 0,
                "retrieval_counts": response.counts,
                "retrieval_timings_ms": response.timings_ms,
                "retrieval": dict(response.diagnostics),
                "config": self.config.to_dict(),
            },
        )
        # diagnostics payload built after total_ms (it re-renders the prompt and serialises the registry)
        timings["metadata_ms"] = round((time.perf_counter() - t_meta) * 1000, 2)
        return out

    def answer_fn(self, question: str) -> RagGenerationResult:
        """Adapter for regulus.evaluation.run_evaluation (answer_fn signature)."""
        out = self.answer(question)
        return RagGenerationResult(
            prompt=question,
            response=out.answer,
            prompt_tokens=out.input_tokens or 0,
            generated_tokens=out.output_tokens or 0,
            seconds=out.timings_ms["total_ms"] / 1000.0,
            diagnostics=out.diagnostics(),
            citations=[c.to_dict() for c in out.citations],
        )

    def describe(self) -> dict[str, Any]:
        describe = getattr(self.retriever, "describe", None)
        retriever = describe() if callable(describe) else {"retriever": type(self.retriever).__name__}
        out = {"rag": self.config.to_dict(), "retriever": retriever, "generator": self.generator.describe()}
        if self.grounding is not None:
            out["grounding"] = self.grounding.describe()
        return out
