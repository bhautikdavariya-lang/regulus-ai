# Adaptive answer shape and evidence relevance (Stage 12 of the answer-quality work)

> Broad question → synthesize the relevant requirements.
> Focused question → answer the specific requirement.
> Explicitly exhaustive question → enumerate the requirements.

The goal is not shorter answers. It is the minimum *structure* needed to answer
the question completely and accurately. Length is still governed by the
Stage 11 policy ([answer_length_policy.md](answer_length_policy.md)), which
this stage does not touch.

*(Naming: the project's training stages are also numbered — `stage12_model_training.md`
is the LoRA run. This document is the answer-shape work that follows the
adaptive answer-length work; "Stage 12" below always means this.)*

## 1. Where it sits in the real runtime path

Traced from `RagPipeline.answer()` (`src/regulus/rag/pipeline.py`) before any
change was made:

```
question
  → plan_query()                 regulus/planning/plan.py      Stage 1: QueryPlan (requirements, kind)
  → retriever.run_plan()         regulus/retrieval/lexical.py  Stage 2: EvidenceRegistry, tiers by identity
  → check_coverage()             regulus/rag/coverage.py       Stage 3: exact evidence per requirement
  → select_evidence()            regulus/rag/selection.py      Stage 3: bounded, requirement-aware selection
  → build_package()              regulus/rag/generation.py     Stage 4: GenerationPackage + GenerationBudget (Stage 11)
  → build_grounded_messages()    regulus/rag/generation.py     system prompt + QUESTION / REQUESTED / EVIDENCE / ANSWER FORMAT
  → generator.generate()         regulus/rag/generator.py      Qwen3-0.6B, greedy, per-question allowance
  → validate_answer()            regulus/rag/validation.py     Stage 4 deterministic checks
  → repair_answer()              regulus/rag/pipeline.py       deterministic repair from exact sources
  → build_answer_citations()     regulus/rag/citations.py
```

The same package renderer is used by Stage 6 to render training examples
(`regulus/stage6/prompting.py`), and Stage 5 evaluates through
`pipeline.answer()` (`regulus/stage5/generation_eval.py`).

## 2. Root cause

It is not retrieval. For "What does 21 CFR 820.10 require?" retrieval is
correct: all twelve rows of the section, tier EXACT. The problem is what the
generator is then given:

* **The two questions "What does 21 CFR 820.10 require?" and "List all
  requirements under 21 CFR 820.10." produced byte-identical packages.** Both
  are one section-level requirement (`kind=single_provision`), so both got
  `shape=single` and the same ANSWER FORMAT line. Nothing in the pipeline
  represented *what kind of answer* was asked for, so no stage could act on it.
* **The evidence reached the model as twelve flat, interchangeable blocks**, each
  labelled `Tier: EXACT (authoritative text of r1)`. The parent/child
  structure (`(b)` → `(b)(1)`…`(b)(4)`, `(c)` → `(c)(1)`, `(c)(2)`) existed in
  the row identities but was never shown to the model. A 0.6B model given
  twelve equal blocks and "cite the source number" defaults to one paragraph
  per block, or (in the most recent run) one paragraph citing only `[1]`.
* **Nothing checked the answer's shape.** Validation checked identities and
  citations per requested provision; with one requested provision (the
  section), a single `[1]` citing the lead-in row satisfied it, even though
  `[1]` supports none of the listed requirements, "if applicable" had been
  dropped, and (c) and (e) were missing (recorded in
  `artifacts/stage5_stage6/run_20260924T070134Z`, question S5-012).
* For a range such as "(a) through (e)", the soft context budget dropped
  `(b)(3)`, `(b)(4)`, `(c)(1)`, `(c)(2)` — subordinate requirements of
  explicitly requested provisions — because children are "optional" structural
  evidence.

## 3. Design

The pipeline order becomes (new steps marked ★):

```
question → QueryPlan → ★AnswerShape → retrieval → coverage
        → selection (★children of requested provisions kept when a shape is set)
        → package (+ ★AnswerPlan: evidence grouped by hierarchy and role)
        → Stage 11 GenerationBudget (unchanged; never sees the shape)
        → prompt (+ ★ANSWER SHAPE / ANSWER PLAN, shape-specific ANSWER FORMAT)
        → generation → validation (+ ★shape checks) → repair (+ ★missing enumeration items)
```

### 3.1 AnswerShape — `regulus/planning/shape.py`

A frozen, serialisable structure derived deterministically from the Stage 1
`QueryPlan` (the existing classifier; no second one, no model call):

| field | meaning |
|---|---|
| `mode` | `synthesis` · `focused` · `enumeration` · `comparison` · `direct` |
| `scope` | `part` · `section` · `subsection` · `multiple` · `topic` · `document` |
| `exhaustive` | the user explicitly asked for every item (or named each one) |
| `requested_units` | canonical labels of the requested provisions / comparison sides |
| `focus_terms` | a topical restriction inside a named provision ("820.10 … about complaints") |
| `signals` | every wording/structure signal that fired, for inspection |
| `rationale` | one line saying why this mode was chosen |

Selection combines *structure* (how many provisions, at what level, whether a
range was expanded) with *wording* (comparison, list/enumerate verbs,
quantifiers bound to a requirement noun, overview words). CFR identifiers are
masked out before wording is read, so "(b)(1)" never looks like a word.

| structure | wording | mode | exhaustive |
|---|---|---|---|
| ≥2 provisions | compare / differ / versus / contrast | comparison | no |
| ≥2 provisions (list, range) | anything else — including "what do … require" | enumeration | yes (every named unit) |
| 1 provision | list / enumerate / itemize; "all/every/each … requirement(s)" (unless an overview word); "in full / in detail / one by one" | enumeration | yes |
| 1 paragraph-level provision | — | focused | no |
| 1 section or part + topical words | "820.10 … about complaints" | focused (on `focus_terms`) | no |
| 1 part | "what is / define" | direct | no |
| 1 section or part | anything else | synthesis | no |
| no provision | compare / list+quantifier / "what is" / otherwise | comparison / enumeration / direct / synthesis (topic or document scope) |

"all" alone is not a signal; it counts only when bound to a requirement noun
("all requirements", "every subsection", "each of the provisions").

### 3.2 Evidence planning — `regulus/rag/answer_plan.py`

`build_answer_plan(shape, sources, requirements)` organises the package's
sources without removing any. Every source lands in exactly one place, which
is what makes "no information loss" checkable (`AnswerPlan.all_indices()`
equals the package's source indices; a test asserts it).

* **Hierarchy** from eCFR identity (section, paragraph path), i.e. existing
  metadata: a section-level request is grouped by top-level paragraph, with
  descendants attached to their parent — `(b)` heads a group containing
  `(b)(1)`…`(b)(4)`; the section row is the *lead-in*. A paragraph-level
  request forms one group per requested provision, with its children attached;
  structural parents become *context*. Part-level requests group by section.
  Guidance and other non-hierarchical sources group by document.
* **Role** per source: `lead_in`, `requirement`, `subordinate`,
  `consequence` (adulteration / regulatory action), `exception`,
  `definition`, `context` (structural parent), `related` (supporting /
  discovery material).
* **Attributes** per source, because a row can be a requirement *and* carry a
  condition *and* point elsewhere: `qualifiers` ("if applicable", "as
  appropriate", "unless …", "except …", "in addition to …"),
  `applicability` (e.g. "Manufacturers of devices that support or sustain
  life …" → the device class it is limited to) and `cross_references`
  (part 830, § 820.7, Clause 7.5.9.1, section 501(h)).
* **Group heading** from the paragraph's own eCFR heading when it has one
  ("(b) Applicable regulatory requirements." → "Applicable regulatory
  requirements"). Nothing is paraphrased; the label is source text.

### 3.3 Selection change (the only one)

When a shape is set, structural **children** of a requested provision are
selected right after the required evidence, bounded by the hard ceilings
instead of the soft budget (reason `subordinate_of_requested`). They stay tier
STRUCTURAL, so coverage, the "EXACT only" budget term and citation tiers are
unchanged. Parents, siblings, supporting and discovery evidence are selected
exactly as before. Nothing is removed from any question's evidence.

### 3.4 Prompt

The system prompt is **unchanged** (it is hashed into the pipeline
fingerprint and shared with Stage 6 training data). Two things change in the
user turn:

1. Under REQUESTED PROVISIONS, *before* the evidence, indented plan lines:

   ```
   REQUESTED PROVISIONS:
   r1: 21 CFR 820.10
     answer shape: synthesized overview (not exhaustive)
     requirement groups, in order: (a) Document [2]; (b) Applicable regulatory requirements [3] with
       sub-requirements the manufacturer must document a system to assign unique device identification ... [4],
       the manufacturer must document procedures for traceability ... part 821 of this chapter, if applicable [5], ...;
       (c) Design and development [8] with sub-requirements Devices automated with computer software [9], ...;
       (d) Devices that support or sustain life [11]; (e) Enforcement [12]
     conditions to keep: "as appropriate" [3]; "if applicable" [5]; (c) Design and development applies only to
       class II, class III, and those class I devices listed ... [8]; ...
   ```

   Sources are named by the citation markers the answer should use. Each
   sub-requirement's handle is its own obligation clause (the words around
   "must"/"shall"), or its whole text when short: source wording, never a
   paraphrase.
2. The ANSWER FORMAT line is chosen by answer mode and is short and
   **list-free**, in the style of the pre-Stage-12 lines.

**Why this layout — learned from live runs, not assumed.** The first version
rendered the plan as a bulleted `ANSWER PLAN` block after the evidence
("- GROUP A: 21 CFR 820.10(a) "Document" = SOURCE 2"). Qwen3-0.6B copied the
block verbatim as its answer (820.10 overview: coverage 2/8, repaired to a
partial extract). A second version moved the organisation into the ANSWER
FORMAT line as prose with the item list inline; the model then copied the item
list (exhaustive question) and the conditions sentence (the (d) question). The
rule that emerged: **this model reproduces whatever list it read last.** Lists
now sit before ~2,000 tokens of evidence, and the last line carries none. A
`prompt_echo` validation error (below) remains as a safety net.

A package built without a shape (Stage 6 training examples, `answer_shape="off"`)
renders byte-for-byte as before.

### 3.5 Validation — `regulus/rag/shape_validation.py`

Shape checks run inside `validate_answer()` when the package has a plan. They
are warnings — reported, never used to shorten or reject an answer — except
three completeness/integrity errors:

| code | severity | fires when |
|---|---|---|
| `evidence_by_evidence` | warning | synthesis/direct: the answer opens a new line with a different provision label for most of the evidence rows |
| `scope_expansion` | warning | focused/comparison: a provision of the same section that was not requested (nor a parent/child of one) is described |
| `enumeration_incomplete` | **error** | explicit enumeration: a material item (requirement, sub-requirement, consequence, exception) is neither cited, named nor substantively present |
| `material_group_uncovered` | **error** | synthesis: a whole requirement group is absent; repair appends the group verbatim |
| `prompt_echo` | **error** (degenerate) | the answer reproduces prompt scaffolding ("SOURCE 3", "GROUP A", "Context only:" …); repair replaces it |
| `qualifier_dropped` | warning | a sentence cites a source carrying "if applicable" / "as appropriate" / "unless" / "except" and neither it nor its paragraph keeps an equivalent |
| `applicability_dropped` | warning | a sentence cites a device-/scope-limited source and says nothing of the limit |
| `synthesis_citation_gap` | warning | a sentence names a cross-reference (part 806, Clause 7.3 …) that none of its cited sources contains but another supplied source does |
| `repeated_statement` | warning | two sentences are near-duplicates (not already degenerate) |
| `qualifier_misapplied` | warning | "if applicable" / "as appropriate" is attached to a cross-referenced requirement whose source carries no such condition |

There is no length check of any kind. `enumeration_incomplete` and
`material_group_uncovered` map to the existing `incomplete` status, and repair
appends the uncovered items or group verbatim from their sources — the same
rule already used for requested provisions the model leaves out. A missing
group started as a warning and was made an error after live runs showed the
0.6B model dropping whole groups from syntheses: a missing material
requirement is a completeness failure whatever the answer's shape.

### 3.6 Stage 11 interaction

The shape never reaches `GenerationBudget`. Stage 11 decides *how much room*;
Stage 12 decides *what structure*. `tokens_for()` is called with the same
arguments as before; the only indirect effect is that an enumeration of a
parent paragraph now carries all its children, and the unchanged structural
term counts them.

### 3.7 Configuration

`RagConfig.answer_shape`: `"adaptive"` (default) or `"off"` (the pre-Stage-12
behaviour, kept so the two can be measured against each other on the same
questions; verified live to reproduce the old answers token for token).

It is part of the pipeline fingerprint (`prompt.answer_shape`), because it
changes what an answer is. Per `regulus/dashboard/fingerprint.py`, adding a
field bumps `FINGERPRINT_VERSION` (1 → 2). Consequence: evaluations recorded
before Stage 12 are no longer presented by the dashboard as evaluations of the
configured system; re-run Stage 5 to get a current one.

Observability: the answering UI's Diagnostics table (`web/index.html`) shows
the shape, its rationale, the evidence groups, the shape checks that fired and
generated/allowance tokens; the dashboard's per-question page shows an "Answer
shape" card for runs that recorded one. Nothing was added to the Overview.

## 4. Results

### 4.1 Tests

| suite | result |
|---|---|
| `tests/test_answer_shape.py` (new: A–J plus shape detection, 78 tests) | 78 passed |
| default suite (`pytest`) | 1014 passed, 1 skipped, 26 deselected |
| `-m "integration and not slow"` (read-only PostgreSQL) | 20 passed |
| `-m slow` (loads the model) | 3 passed, 3 failed — the same 3 fail on the unmodified code (pre-existing) |

The skip is `test_dashboard_health.py::test_the_real_dashboard_reports_the_current_model_honestly`:
"no current evaluation in this repository". That is the intended consequence
of fingerprinting `answer_shape` (§3.7): the stored Stage 5 runs measured the
pre-Stage-12 pipeline, so the dashboard no longer presents them as the
current system's evaluation. A fresh Stage 5 run restores it.

Assertions changed on purpose: `test_stage5_identity.py` pinned
`FINGERPRINT_VERSION == 1` (now 2, per the module's own rule for adding a
fingerprint field).

### 4.2 Live evaluation

`python scripts/evaluate_answer_shape.py` on
`data/evaluation/datasets/answer_shape_v1.jsonl` (9 questions, expectations
fixed by hand against the verified 820.10 / Part 821 text), Qwen3-0.6B base,
greedy, CPU. `answer_shape=off` and `adaptive` were run back to back on the same
machine state. `off` reproduces the pre-change code exactly (same token count
on every question), so it is the "before". Artifacts:
`artifacts/answer_shape/{shape_off,after,before}_*` (`superseded_*` are the
prompt iterations described in §3.4).

Each dimension is reported separately; nothing is combined.

| id | question | shape detected | coverage raw (off → after) | coverage after repair | tokens (off → after) | gen s (off → after) | shape findings on the after answer |
|---|---|---|---|---|---|---|---|
| AS-01 | What does 21 CFR 820.10 require? | synthesis / section | 8/8 → 8/8 | 8/8 | 696 → **390** | 68 → **42** | qualifier_misapplied |
| AS-02 | …820.10(b)(2) require? | focused / subsection | 2/3 → 2/3 | 2/3 | 46 → 46 | 5 → 5 | none |
| AS-03 | List all requirements under 21 CFR 820.10. | enumeration / section / exhaustive | 9/9 → **7/9** | 9/9 | 679 → 528 | 59 → 50 | enumeration_incomplete (repaired), synthesis_citation_gap, qualifier_misapplied |
| AS-04 | Explain 21 CFR 820.10(a) through (e). | enumeration / multiple | 5/5 → **3/5** | 5/5 | 395 → 455 | 33 → 43 | requirement_not_addressed (repaired) |
| AS-05 | Compare 820.10(c) and 820.10(d). | comparison | 4/4 → 4/4 | 4/4 | 192 → 264 | 16 → 23 | synthesis_citation_gap; citation mismatch (repaired) |
| AS-06 | …820.10(d) require? (conditional) | focused / subsection | 3/4 → 3/4 | 3/4 | 70 → 70 | 7 → 7 | none |
| AS-07 | …(b)(1) through (b)(4) require? | enumeration / multiple | 4/4 → 4/4 | 4/4 | 257 → 187 | 24 → 18 | none |
| AS-08 | …820.10(b)(3) require? (cross-ref) | focused / subsection | 3/3 → 3/3 | 3/3 | 43 → 43 | 5 → 5 | none |
| AS-09 | What is Part 821? | direct / part | 1/1 → 1/1 | 1/1 | 471 → 395 | 42 → 35 | none |

Answer shape was detected correctly on 9/9. Qualifier presence ("if
applicable", "as appropriate"): kept on 9/9 in both runs. Out-of-scope terms
in focused/comparison answers: none in either run. Truncation: none in either
run. Prompt tokens rose by 40–580 (the plan lines), e.g. 1,728 → 2,087 on AS-01.

### 4.3 Before / after for "What does 21 CFR 820.10 require?"

**Before** (`off`, 696 tokens, 68 s): twelve paragraphs, one per evidence row
("21 CFR 820.10(a) requires…", "21 CFR 820.10(b)(1) requires…" … "(e)"), every
one citing `[1]` — the lead-in row, which supports none of them. The old
validator called it valid. The new checks flag it: `evidence_by_evidence` and
nine `synthesis_citation_gap`s ("part 806 comes from SOURCE 7, which the
statement does not cite (it cites 1)").

**After** (`adaptive`, 390 tokens, 42 s): one synthesized overview — the QMS
requirement, then UDI (part 830), traceability (part 821, if applicable),
complaint reporting (part 803) and advisory notices (part 806) folded together,
design and development for class II/III and listed class I devices, the
life-supporting device requirement "as appropriate", and adulteration under
501(h). **No material requirement was lost (8/8 points, 11/11 items).**

What is still wrong with it, and is reported: it is one dense paragraph
rather than a paragraph per group; it carries a single `[4][5]` at the end
instead of per-claim markers; and it attaches "if applicable" to the part 830
(UDI) obligation, which in the source is unconditional —
`qualifier_misapplied` flags exactly that.

## 5. Limitations (honest)

* **The 0.6B model follows structure unevenly.** It reproduces whatever list
  it read last (§3.4). Enumerations sometimes stop early — twice here after
  (c)(2) — so *raw* completeness on the two exhaustive questions was lower than
  the old verbatim transcription (7/9 vs 9/9, 3/5 vs 5/5). The new checks catch
  it and repair restores the missing items verbatim (final 9/9, 5/5), but the
  raw regression is real.
* **Citations in syntheses are sparse.** The model often puts one marker at the
  end of a synthesized paragraph. `build_answer_citations` still lists every
  exact source of the addressed provision, so traceability to sources survives,
  but per-claim attribution does not. `synthesis_citation_gap` only checks
  sentences that carry a marker.
* **Misplaced qualifiers are detected, not fixed.** `qualifier_misapplied`,
  `qualifier_dropped`, `applicability_dropped` and `synthesis_citation_gap` are
  warnings; repair does not rewrite a sentence.
* **Classification is heuristic.** Deterministic regular expressions over the
  question with identifiers masked. It was right on all 22 table cases and 9
  live questions, but it will misread phrasings it has not met (e.g. a topic
  word the stop lists do not cover becomes a false `focus_terms`; the evidence
  planner falls back to synthesis when no source mentions it).
* **Evidence coverage checks are lexical.** An item counts as represented if it
  is cited, named, its cross-reference appears, or half its content words
  appear. A paraphrase with different words can be missed (a false
  `enumeration_incomplete`/`material_group_uncovered`, whose repair then
  appends text the answer already had).
* **Role detection is pattern-based** (lead-in, consequence, exception,
  definition) and tuned on eCFR paragraph conventions.
* **Answer efficiency was not added as a metric.** The script reports
  `tokens_per_point_if_complete` only for complete answers, but nine
  hand-labelled questions are too few to publish a reliable efficiency figure.
* **The evaluation set is small** (9 questions, one section family). It is a
  regression check, not a benchmark. Stage 5 should be re-run for the full
  picture (it now records `answer_shape` and `evidence_plan` per question).

## 6. Future work

1. Re-run Stage 5 on the configured pipeline so the dashboard has a current
   evaluation again, and compare `valid_raw`, completeness and citation
   metrics against the last pre-Stage-12 run.
2. Per-group generation for large syntheses/enumerations (one short model call
   per group, assembled deterministically) — would fix sparse citations and
   early stops, at a latency cost to be measured.
3. Training data in the Stage 12 prompt format (the Stage 6 renderer can pass
   an `AnswerShape`) so a fine-tuned model learns the shapes rather than being
   instructed.
4. Sentence-level repair for `qualifier_misapplied` and
   `synthesis_citation_gap` (replace the sentence with the cited item's
   verbatim text), mirroring the existing mismatched-statement repair.
5. Extend `answer_shape_v1.jsonl` beyond 820.10 / Part 821.
