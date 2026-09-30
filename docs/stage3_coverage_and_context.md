# Stage 3: Evidence Coverage, Selection and Protected Context

Stage 3 sits between the Stage 2 `EvidenceRegistry` and the prompt. It
decides, deterministically and without the model, whether each explicit
requirement is covered, which evidence goes into the context and in what
order, and what the pipeline does when an explicit request cannot be fully
supported. The renderer, the grounding gate and the generator are unchanged.

```
EvidenceRegistry
   │
   ▼  regulus.rag.coverage.check_coverage()
CoverageReport            state: NO_EXPLICIT_REQUIREMENTS | COMPLETE | INCOMPLETE
   │                      per requirement: exact | structural_only | supporting_only | discovery_only | unresolved
   ▼  regulus.rag.selection.select_evidence()
Selection                 phase 1 required (protected)  →  2 structural  →  3 supporting  →  4 discovery
   │                      soft budget for optional evidence, hard ceilings for everything
   ▼  regulus.rag.context.render_selection()
ContextBundle             SOURCE blocks (unchanged format) + NOTE lines; sources carry tier / requirement_ids / protected
   │
   ▼  RagPipeline.answer()
grounding gate → incomplete-coverage decision → no-context rule → generation
```

## 1. Coverage model

`check_coverage(registry)` reads only Stage 2 tiers and associations:

| Requirement has | Status | Satisfies the explicit request? |
|---|---|---|
| exact evidence (`satisfies` contains it) | `exact` | yes |
| only parent/child rows | `structural_only` | no |
| only same-section siblings (any method) | `supporting_only` | no |
| only broad-method hits tagged for it | `discovery_only` | no |
| nothing | `unresolved` | no |

State is `COMPLETE` only when every explicit requirement is `exact`;
`INCOMPLETE` otherwise; `NO_EXPLICIT_REQUIREMENTS` when the plan names no
CFR provision (general questions, docket questions). There is no threshold
and no partial credit: four requested provisions with three exact rows is
`INCOMPLETE`. Parent, child, sibling, guidance and discovery evidence never
promote a requirement.

## 2. Selection model

`select_evidence(registry, policy, optional_filter)`:

* **Required** = tier `exact` that satisfies a requirement, plus the chunks
  of a requested docket. Kept in registry order (requirement order, then
  document order), full text up to `required_max_chars_per_result` (4,000,
  longer than any eCFR paragraph), protected, bounded only by the hard
  ceilings.
* **Optional** = structural, then supporting, then discovery, each in the
  registry's order (structural by requirement then document order, the
  others by score). Optional sources spend what the soft budget leaves.
  The pipeline's usefulness rule (trigram similarity cut-off,
  contextual-only exclusion) applies to supporting and discovery only;
  structural evidence is identity-based and exempt.
* One registry entry appears at most once; a parent shared by four
  requirements is one source with `requirement_ids = (r1, r2, r3, r4)`.
* No score is combined across tiers. Scores never move anything between
  tiers.

## 3. Context budget

`ContextPolicy` keeps its three limits as the **soft budget** and adds
ceilings:

| Field | Default | Applies to |
|---|---|---|
| `max_results` | 8 | optional sources (total count while adding optional) |
| `max_chars_per_result` | 1,200 | optional sources |
| `max_total_chars` | 3,600 | optional sources (squeeze to fit if ≥ 200 chars remain, else drop) |
| `required_max_chars_per_result` | 4,000 | required sources (truncation marked and reported) |
| `hard_max_results` | 24 | everything |
| `hard_max_total_chars` | 9,000 | everything |

Required evidence may exceed the soft budget (a whole section of 12 rows is
4,828 chars and is kept in full). If required evidence alone would exceed a
hard ceiling, the remaining required sources are dropped with reason
`hard_ceiling_chars` / `hard_ceiling_count`, listed in
`selection.required_dropped`, and `selection.overflow` is true. Nothing is
dropped silently. Hard ceilings are raised automatically to at least the
soft values so legacy configurations remain valid.

## 4. Incomplete coverage behaviour

`RagConfig.incomplete_behavior` (default `"partial"`):

| Coverage | Model called? | Result |
|---|---|---|
| `NO_EXPLICIT_REQUIREMENTS` or `COMPLETE` | yes | as before; `coverage_action = "answer"` |
| `INCOMPLETE`, some requirements exact | yes, with a NOTE naming the missing provisions | model answer + deterministic sentence "Not found in the available eCFR data: …"; `coverage_action = "answer_partial"` |
| `INCOMPLETE`, none exact | no | deterministic "The available eCFR data does not contain … I will not infer its contents."; `coverage_action = "refuse_unsupported"` |

The Stage 13 grounding gate still runs first and keeps its own refusals.
`incomplete_behavior = "model"` restores the legacy path.

Example, `What does 21 CFR 820.10(b)(5) require?` on the live database:
coverage `INCOMPLETE` (`structural_only`, note "parent 21 CFR 820.10(b)
exists"), selection = the parent row and one guidance chunk, none
protected, model not called, answer returned in 0.2 s.

`What do 820.10(b)(1) through 820.10(b)(5) require?`: (b)(1)–(b)(4) exact
and protected, (b) structural for all five, (b)(5) `structural_only`; the
model answers the four and the sentence naming (b)(5) is appended.

## 5. Diagnostics

`RagAnswer.metadata` gains `coverage`, `selection` and `coverage_action`;
`RagAnswer` gains `coverage` and `selection` objects. The UI's raw JSON
carries `plan`, `evidence`, `coverage`, `coverage_action`, `selection`, and
each source's `tier`, `requirement_ids`, `protected`, `selection_reason`.

```
coverage:  state, complete, missing, missing_labels, total_requirements,
           exact_requirements, structural_only_requirements,
           supporting_only_requirements, discovery_only_requirements,
           unresolved_requirements,
           requirements: [{requirement_id, canonical, status, satisfied,
                           exact_evidence_ids, structural_evidence_ids,
                           supporting_evidence_ids, discovery_evidence_ids, note}]
selection: selected: [{index, evidence_id, key, citation, tier, requirement_ids,
                       protected, reason, chars, block_chars, truncated}],
           dropped:  [{evidence_id, citation, tier, requirement_ids, reason, required}],
           policy, total_chars, overflow, required_count, required_chars,
           optional_count, required_dropped, required_truncated,
           optional_dropped, soft_budget_exceeded_by_required, tier_counts
```

## 6. Files

| File | Change |
|---|---|
| `src/regulus/rag/coverage.py` (new) | `CoverageReport`, `RequirementCoverage`, `check_coverage()` |
| `src/regulus/rag/selection.py` (new) | `Selection`, `SelectedEvidence`, `DroppedEvidence`, `select_evidence()` |
| `src/regulus/rag/context.py` | `ContextPolicy` ceilings, `ContextSource` provenance fields, `render_selection()`; `build_context()` unchanged |
| `src/regulus/rag/prompt.py` | `coverage_note()`, `incomplete_coverage_answer()`, `unresolved_provisions_statement()` |
| `src/regulus/rag/pipeline.py` | `build_bundle()`, `is_useful()`, `incomplete_behavior`, coverage-aware answer decision, metadata |
| `scripts/serve_ui.py` | response carries the new metadata (no page change) |
| `tests/test_evidence_coverage.py` (new) | 24 behaviour tests |
| `audit/stage3_context_check.py` (new) | read-only live validation |

Measured: coverage + selection + rendering takes 0.2 to 0.5 ms per
question on the live database; retrieval is unchanged from Stage 2.

## 7. Limitations (Stage 4 and later)

* The prompt is unchanged; sources are not labelled as requested or
  supporting for the model. The model still enumerates four provisions
  within a 128-token cap and can be cut off mid-list.
* Discovery rows for an unresolved section (numerically similar sections)
  still reach the context as optional evidence when budget remains.
* A docket question that also names a CFR provision with no exact row is
  refused deterministically even though the docket chunks were found.
* Guidance is never linked to a specific requirement.
* Answer validation, claim-level citation support, per-source labelling in
  the prompt and conversation state are not implemented.
