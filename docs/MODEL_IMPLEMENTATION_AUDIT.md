# Model Implementation Audit

Date: 2026-10-02. Diagnostic phases 0–4 of the capacity-vs-implementation investigation. Nothing in the
production pipeline was modified. Model: Qwen/Qwen3-0.6B, no adapter.

Evidence files: `artifacts/diagnostics/model_probe/phase2_runtime.json`, `phase1_sanity.json`,
`phase3_prompts.json`, `prompts/*.txt`.

## 1. Inventory: what the implementation actually is

| # | Item | File / symbol | Current value | Could it affect a capability measurement? | Confidence |
|---|---|---|---|---|---|
| 1 | Model id | `configs/model.yaml` → `model.id`; `src/regulus/config/settings.py` | `Qwen/Qwen3-0.6B` | Yes — defines the arm | High |
| 2 | Model revision | runtime `config._commit_hash` | `c1899de289a04d12100db370d81485cdf75e47ca` | Yes | High |
| 3 | Tokenizer | `src/regulus/model/loader.py::load_tokenizer` | `Qwen2Tokenizer`, `tokenizer.json` sha256 `aeb13307…dae4` | Yes | High |
| 4 | Chat template | tokenizer-supplied; applied in `inference/generate.py::generate_chat` | sha256 `a55ee1b1…74a8`, 4,168 chars, exposes `enable_thinking` | Yes | High |
| 5 | Model loading | `model/loader.py::load_model` → `AutoModelForCausalLM.from_pretrained` + `.to(device)` + `.eval()` | local cache `models/`, `local_files_only=True` in evaluation | Yes | High |
| 6 | Inference entry | `rag/generator.py::QwenGenerator.generate` → `inference/generate.py::generate_chat` | single turn, system + user | Yes | High |
| 7 | Generation config | `system_identity.py::configured_generation_config` | greedy: `do_sample=False`, thinking off, `max_new_tokens` = ceiling 2048 | Yes | High |
| 8 | Prompt construction | `rag/generation.py::build_grounded_messages` / `render_package` / `render_source` | system = `GROUNDED_SYSTEM_PROMPT` (10 rules), user = question + requested provisions + sources + notes + format line | **Yes — see defect D1** | High |
| 9 | Evidence formatting | `render_source` | `SOURCE n` / `Tier:` / `Corpus:` / `Citation:` / `Heading:` / `Text:` | **Yes — see defect D1** | High |
| 10 | Context handling | `generate_chat`; budget from `answer_length` policy | prompt 1,314–2,645 tokens measured; window 40,960 | No — 38k+ tokens spare | High |
| 11 | Output parsing | `inference/chat.py::split_thinking`; decode with `skip_special_tokens=True` | separates `<think>` blocks | Low — thinking is off | High |
| 12 | Citation post-processing | `rag/citations.py` via `pipeline.build_citations`, `strip_invalid_citations` | markers validated against the source list; invalid stripped | Yes — see defect D3 | High |
| 13 | Repair / retry | `rag/pipeline.py::repair_answer`, `repair_with_fallback` | in-place row replacement, invented-sentence removal, premise fallback, withholding | **Yes — see defect D2** | High |
| 14 | Truncation | budget cap only; no prompt truncation observed | 1 of 10 captured prompts hit the generation cap (E-003) | Yes, narrowly | High |
| 15 | Stop conditions | `generate_chat`: eos from `generation_config` + tokenizer; `inference/repetition.py::RepetitionStop` at the 3rd normalised repeat | eos `<\|im_end\|>` 151645 and 151643 | No defect found | High |
| 16 | dtype | `model/device.py::resolve_dtype` | `float32` (auto → fp32 on CPU) | Yes — must be held constant across arms | High |
| 17 | Quantisation | none | — | — | High |
| 18 | Device / backend | `resolve_device("auto")` | `cpu`; MPS available but never auto-selected; CUDA absent | Yes | High |
| 19 | Max input context | `config.max_position_embeddings` | 40,960 | No | High |
| 20 | Max generated tokens | `answer_length` policy | adaptive, floor 256, ceiling 2048; budgets of 384 and 1,696 observed | Narrowly — see D2 | High |
| 21 | Thinking mode | `configured_generation_config` | **disabled** | Yes — untested until phase 8 | High |
| 22 | Benchmark vs production path | `scripts/run_acceptance_test.py` builds the same `RagPipeline` with `configured_rag_config` + `build_retriever` + `load_generator` | **identical path** | — | High |

**Intended vs runtime:** no discrepancy. 596,049,920 parameters, `Qwen3ForCausalLM`, sdpa attention,
float32, cpu, weights sha256 `f47f7117…874b`, matching the frozen baseline manifest.

One latent hazard, not a defect: the model's own `generation_config` ships `do_sample=True,
temperature=0.6, top_p=0.95`. Greedy decoding holds only because `configured_generation_config` overrides
it and `generate_chat` passes sampling arguments **only** when `do_sample` is true. Any code path that
forgets that override silently becomes stochastic.

## 2. Confirmed defects

### D1 — Whole-part requests collapse evidence tiering and ordering. Severity: HIGH

**Mechanism.** When the question names a part rather than a section, the planner emits a single
requirement for the whole part (`r1: 21 CFR part 111`). Every retrieved section in that part then
satisfies "EXACT (authoritative text of r1)", so `render_source` labels all of them identically, and they
are emitted in citation-string order. The prompt therefore contains ~20 sources that are
indistinguishable in authority and sorted alphabetically rather than by relevance.

**Evidence.** `prompts/S-003.txt`: question asks for personnel qualification requirements; 22 sources, all
`Tier: EXACT (authoritative text of r1)`; SOURCE 1 = 111.103, SOURCE 2 = 111.105, keyed section 111.12 at
SOURCE 10. The delivered answer came from SOURCE 1. The same signature — "written procedures for quality
control operations" — recurs across S-001…S-024 for questions about hygiene, sanitation, records and
specifications.

**Blast radius.** Planner run over all 300 benchmark questions:

| Request granularity | Questions |
|---|---:|
| Part-level only (whole part treated as the request) | **112** |
| No provision named (general) | 168 |
| Section-level | **19** |
| Mixed part + section | 1 |

Part-level rows by type: Direct Lookup 73, Distinction 12, Application 9, Cross-Reference 8, Negative
Control 8, Temporal 1, Scope 1.

**Why it matters for the capacity question.** For 112 questions the measurement did not ask "can the model
reason over the right provision?" It asked "can the model pick the right provision out of twenty
equally-labelled ones in alphabetical order?" Those are different tasks, and only the first is the one the
model ladder is meant to test.

### D2 — Suppression converts a generation defect into a non-answer. Severity: MEDIUM

46 of 299 answers were replaced by the "could not be validated" notice and 19 declined before generation —
65 non-answers. The machinery is working as designed, and in several rows it demonstrably prevented a
fabrication from reaching the user. But the final answer then carries no information, and a reader of the
results cannot tell a model failure from a validation failure without the raw output. E-003 shows the
costly variant: 1,696 generated tokens, no end-of-turn, 158 seconds, then withheld.

### D3 — Citation markers are model-chosen, then filtered. Severity: MEDIUM

Rule 6 asks the model to number its own sources; `strip_invalid_citations` removes markers that do not
resolve. Measured over the 299 answers: 107 carry no citation at all, 13 use a marker with no matching
source, and 8 answers are substantively correct but mis-cited. The model is being asked to do bookkeeping
the pipeline could do deterministically, and the rubric's citation gate (99%) is then scored on it.

### D4 — Prompts were not persisted. Severity: MEDIUM (now closed)

`answers.jsonl` stores question, evidence labels, citations, raw output and the final answer, but no prompt
and no prompt hash, so the 300-question run's prompts could not be verified after the fact.
`scripts/model_probe_phase3.py::RecordingGenerator` now captures and hashes the exact production prompt;
10 are archived under `artifacts/diagnostics/model_probe/prompts/`.

## 3. Risks checked and NOT found

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Wrong model or revision loaded | Not found | Runtime commit hash and weights sha256 match the manifest |
| Tokenizer or chat-template mismatch | Not found | Tokenizer and template hashes recorded; template applied by the model's own `apply_chat_template` |
| Adapter accidentally attached | Not found | `settings.model.adapter` is `None`; parameter count matches the base model |
| Sampling left on | Not found | `do_sample=False`; sampling args not passed. Model defaults would have sampled — override is load-bearing |
| Prompt truncation | Not found | 1,314–2,645 tokens vs a 40,960 window |
| Context-length pressure | Not found | Sanity suite clean to 3,572 tokens; prompts far below the window |
| Token budget too small | Not found as a general cause | Budgets 384/1,696; 9 of 10 ended on end-of-turn; one hit the cap in a repetition loop |
| System message landing in user content | Not found | Captured prompts show correct `<\|im_start\|>system` / `user` framing |
| Output parsing corrupting good text | Not found so far | Raw and final captured side by side; divergence is validation/repair (D2), not parsing |
| Benchmark using a different inference path | Not found | `run_acceptance_test.py` builds the identical pipeline objects |

## 4. Sanity suite result (phase 1)

Minimal prompt, no retrieval, no post-processing, mechanical string scoring: **16 of 16 passed** —
factual extraction 3/3, instruction following 2/2, multi-step reasoning 3/3, context utilisation 2/2,
negative evidence 2/2, long context 4/4 (575 → 3,572 prompt tokens).

The model performs two-step rule application and admits missing evidence **when the prompt is clean**. This
does not show regulatory competence, and it is not evidence that 0.6B is adequate for the benchmark. It
shows that the inference implementation is not the thing breaking those behaviours.

## 5. Open items for the remaining phases

- Phases 5–8 (running): the same 36 stratified questions under production, simplified and focused-evidence
  prompts, plus sampling, half-budget and thinking-mode arms. This quantifies D1 directly.
- Phase 9 (4B/8B): **cannot run on this machine.** 8 GB of RAM cannot hold a 4B model at float32, and
  quantising it would break the equal-dtype rule that makes the comparison valid. Designed and frozen for
  a CUDA host.
