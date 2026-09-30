# Production Model Selection Audit

Date: 2026-09-30. Inspection only: no code, model, database, benchmark, dataset or artifact was changed.

The only file this audit writes is this report. `artifacts/dashboard/registry.json` shows as modified in git
because the running dashboard server rewrites it at start-up; the audit did not touch it.

Labels used throughout:
- **[Repo]**: a fact read from this repository or measured on this machine.
- **[Estimate]**: an engineering estimate, not measured here.
- **[External]**: general knowledge about models, hardware or serving stacks, to be verified before any commitment.

---

## 1. Executive summary

* **The architecture is ready for a larger model; the hardware is not.**
  * *Swappable [Repo].* Everything except the inference layer is model-independent. Loading is generic Hugging
    Face (`AutoModelForCausalLM`/`AutoTokenizer`), and the model id is one config value. Another Qwen3 size
    loads by configuration alone.
  * *The machine's limit [Repo].* The development machine is an 8 GB Apple M2 that is already swapping with the
    0.6B model loaded.
  * *No quantization path [Repo].* The code has no quantized-inference or remote-serving option, so nothing
    above about 4B can run here.
* **The remaining failures are mostly model capacity, but not only that.**
  * *Capacity [Repo].* Of 18 failing diagnostic questions (Stage 6, developer-reviewed), 9 fail under every
    one of 11 prompt/context representations, including exact-evidence-only. Two more are fixed only by prompt
    variants that break other questions.
  * *Not capacity [Repo].* Seven are retrieval, scope policy, validator or evaluation problems that no model
    will fix.
* **The evaluation apparatus is not yet strong enough to pick a production model on its own.**
  * *Keys [Repo].* All 300 benchmark keys are unverified by an SME.
  * *Concentration [Repo].* 33 of the 79 diagnostic questions concern one section (21 CFR 820.10).
  * *Validator blind spots [Repo].* The validator misses row misattribution and invented or omitted conditions;
    three Stage 6 errors were visible only to developer review.
* **Recommendation.** Do not stay at 0.6B for production. Do not treat 1.7B as the next production candidate.
  Evaluate a **model ladder** on identical frozen evidence:
  * **4B** is the smallest serious candidate;
  * **8B** is the likely production candidate;
  * **14B** is the reference;
  * **one 30B-class model** is the upper bound.
  * **1.7B** is an optional, free local slope point only.

  Candidates at 8B and above must run on hardware other than this laptop. Stage 7 should first build the
  backend seam and the frozen-evidence harness and harden the validator's scoring, then run the ladder. No
  training now.

---

## 2. Current architecture (production answering path)

```text
question
 → plan_query                    planning/plan.py              [independent]  requested provisions, docket, kind
 → question_view                 rag/pipeline.py               [independent]  AnswerShape (planning/shape.py) + QuestionAnalysis
                                                                              (planning/intent.py: type, yes/no, scope)
 → retrieve (run_plan)           retrieval/lexical.py          [independent]  exact CFR/docket fetch, full-text, OR-fallback, trigram;
                                                                              PostgreSQL read-only
 → check_coverage                rag/coverage.py               [independent]  per-requirement exact/structural/supporting/discovery
 → select_evidence (+required_only when complete and self-contained)
                                 rag/selection.py              [independent*] Stage 6 context policy (*tuned on 0.6B)
 → build_package                 rag/generation.py             [independent*] answer plan (rag/answer_plan.py), token budget
                                                                              (GenerationBudget), prompt text (*format tuned on 0.6B)
 → answerability gate            rag/answerability.py          [independent]  8 states; 5 block generation
   ├─ blocked → safe fallback    rag/fallback.py               [independent]  deterministic answer, model not called
   └─ allowed ↓
 → build_grounded_messages       rag/generation.py             [independent]  system prompt + user turn (list of messages)
 → Generator.generate            rag/generator.py → inference/generate.py
                                                               [MODEL-DEPENDENT] chat template, model.generate (greedy,
                                                                              thinking off), streaming callback, first-token timer
 → normalize (structured only)   rag/answer_quality.py         [independent]
 → validate_answer               rag/validation.py + shape_validation.py
                                                               [independent]  citations, coverage, qualifiers, figures, degenerate
 → repair_with_fallback          rag/pipeline.py + fallback.py [independent]  extractive / withheld; a still-ungrounded answer is never shown
 → citations                     rag/citations.py              [independent]  authoritative citation objects, never model-written
 → metadata / trace              observability/trace.py        [independent]  raw output, repair input/output, gate decision
 → UI / API                      scripts/serve_ui.py, web/index.html
                                                               [independent]  /api/ask, /api/ask/stream (NDJSON), one inference
                                                                              at a time (global lock)
```

Only **one box is model-dependent**: `Generator.generate` and the code beneath it. Several independent boxes
carry **0.6B-tuned parameters** (marked `*`): the prompt layout, the context policy and the token budgets. They
work with any model, but they were optimised against 0.6B weaknesses (§7, class C).

Main failure modes per stage, from Stages 4–6 [Repo]:

| Stage | Failure modes |
|---|---|
| Planning | a reference target read as the requested provision (S5-090) |
| Retrieval | the answering provision is never a candidate (S5-090, S5-061); OR-fallback noise on general questions |
| Selection | related context distracts 0.6B (Stage 6) |
| Gate | patterns can misfire (PROBABLE states); general questions cannot be judged (UNKNOWN) |
| Generation | omissions, qualifier drift, misattribution, false-premise agreement, degeneration |
| Validation | misses row misattribution, omitted or invented conditions, applicability overstatement; accepts uncited answers |
| Repair / fallback | sound since Stage 5 (no ungrounded repair shown) |

---

## 3. Model layer audit [Repo]

| Item | Finding |
|---|---|
| Model | `Qwen/Qwen3-0.6B` (`configs/model.yaml`, env `REGULUS_MODEL_ID`) |
| Revision / weights | snapshot `c1899de289a0…`; `model.safetensors` sha256 `f47f71177f32…`; architecture `Qwen3ForCausalLM`, 28 layers, hidden 1024, 16 attention heads / 8 key-value heads, vocab 151,936, tied embeddings, stored bf16 |
| Tokenizer | Qwen3 tokenizer via `AutoTokenizer` (same file set) |
| Loading | `model/loader.py:load_model`: `AutoModelForCausalLM.from_pretrained(id, dtype)` → `.to(device)` → `.eval()`. Generic; no `trust_remote_code`, no Qwen-specific code |
| Inference | `inference/generate.py:generate_chat`: `apply_chat_template(..., enable_thinking=)` → `model.generate` → decode; returns tokens, timings, a finished flag |
| Decoding in the pipeline | greedy, thinking off, forced by `system_identity.configured_generation_config`. `configs/model.yaml` still says `do_sample: true`, temperature 0.7, for the non-RAG scripts. **Inconsistency, not a defect**: the answering pipeline never samples |
| Context length | 40,960 tokens (model); prompts use 691–2,422 tokens (median 1,326 in Stage 6) |
| Max generated tokens | adaptive per-question budget (min 256, per provision 160, evidence ×1.4), hard ceiling 2,048 |
| Quantization | **none**. float32 on CPU (default), float16 on MPS opt-in; no int8/int4, GGUF, MLX or AWQ path |
| Devices | CPU default; MPS opt-in (Stage 2: 2.4× faster, 5 of 60 answers differ from CPU); CUDA supported by code, never available here |
| Memory | CPU fp32 RSS ≈ 2.9–3.9 GB; MPS fp16 ≈ 2.5 GB (Stage 2) |
| Initialisation | 1.6–3.9 s load with weights in page cache (Stage 2, performance baseline) |
| Throughput | CPU fp32 decode median 12.6–13.2 tokens/s, prefill ≈ 775 tokens/s, first token 1.7–1.9 s; MPS fp16 decode 28.2 tokens/s, first token 0.82 s |
| Streaming | `inference/streaming.py:TextCallbackStreamer` (transformers `TextStreamer`); NDJSON `/api/ask/stream`; drafts are provisional and the validated answer is final |
| Concurrency | `serve_ui.py`: `ThreadingHTTPServer` with a global `_LOCK`, **one inference at a time, no batching** |
| Coupling to Qwen3-0.6B | model id default in `config/settings.py`; `QwenGenerator` / `load_qwen_generator` names; `enable_thinking` template kwarg; `<think>` splitting in `inference/chat.py`; fine-tune paths `models/qwen3-0.6b-lora`. **None of these blocks another Qwen3 size**; other families need small adapter changes (§7) |

**Swappability verdict [Repo].**
* **Another Qwen3 dense size** (1.7B/4B/8B/14B/32B) is a configuration change, *if* it fits the device
  un-quantized with transformers.
* **Anything quantized or served remotely** needs a new `Generator` implementation. The protocol already exists
  (`rag/generator.py:Generator`), which makes this a bounded change.

---

## 4. Stage 1–6 findings (engineering implications)

| Stage | Result [Repo] | Implication for model selection |
|---|---|---|
| Performance baseline | decode is 78 % of answer time; memory-bandwidth bound (each token reads all weights) | decode speed scales ≈ inversely with weight bytes, so model size and precision set latency |
| 1 Streaming | one generation call, streamed; validated answer is final | model-independent; works for any HF model, and needs an adapter for server backends |
| 2 Device / dtype | MPS fp16 2.4× faster; 5/60 answers differ from CPU fp32; model + runtime ≈ 2.5 GB; lowest free memory 421 MB with MPS fp32 | 8 GB unified memory has no room for a model above ≈ 2.5–3 GB of weights alongside PostgreSQL and the OS |
| 3 Answer quality | structured mode opt-in; prompt/profile tuning | prompt tuning showed small, mixed gains on 0.6B |
| 4 Failure observatory | taxonomy F01–F21; traces; raw output preserved | the measurement infrastructure is model-independent and reusable as is |
| 5 Answerability gate | PASS 39 → 45 (44 after correction), FAIL 22 → 16; 16 generations blocked; F05 3 → 0 | the gate removes a class of failures a larger model would not have fixed (insufficient evidence) |
| 6 Generation quality | 11 representations; exact-evidence context adopted with safeguards; PASS 44 → 46 (reviewed); 9 failures persist under every representation; every refinement traded one fix for one regression | **the capacity ceiling of 0.6B is reached**; further prompt work on 0.6B has negative expected value |
| 12–14 LoRA fine-tuning (earlier) | Stage 12: 1 improved, 13 regressed; Stage 13: reviewer mean 0.556 vs base 1.11; Stage 14 stalled, verdict never written; one epoch = 45.7 h here | fine-tuning 0.6B on this machine was tried three times and did not help; the data design, not only capacity, was part of the cause |

---

## 5. Remaining failure taxonomy (Stage 6 final, developer-reviewed) [Repo]

18 failing questions plus 2 NEEDS_REVIEW, classified with the exact-evidence condition and up to 6 distinct
prompts each (`artifacts/generation_quality/variant_outcomes_remaining_failures.json`).

| Root cause | Questions | Evidence |
|---|---|---|
| **1. Model capability** | S5-006, S5-010, S5-012, S5-053, S5-091, S5-101, AS-01, AS-06, BM-S-019 | no representation clean, including exact evidence only |
| 1b. Capability, with a prompt fix that regresses others | S5-100, BM-F-002 | clean only under h2 or h3, both rejected as net-mixed |
| **2. Retrieval** | S5-061 (UDI content definition never retrieved), S5-090 (the referring provision is never a candidate; text search does not find it) | answer absent from the evidence |
| **3. Evidence selection** | S5-024 (clean with exact evidence only; the fragment safeguard keeps the Stage 5 context) | Stage 6 experiments |
| **4. Answerability** | S5-090 is a correct block; no false block found | Stage 5 dry run over 379 questions |
| **5. Prompt / context** | (1b) above | — |
| **6. Validator weakness** | S5-007 (omitted conditions + invented qualifier pass), S5-101 (row misattribution is only a warning), uncited answers pass (5 questions) | developer review |
| **7. Repair / fallback** | none open | failed-repair safety held |
| **8. Product / scope policy** | S5-080, S5-082 (general knowledge answered; critical) | OR-fallback signal is 5/6 accurate, not adopted |
| **9. Data** | BM-S-001 (part-level general question, degenerate on broad Part 111 evidence) | retrieval breadth |
| **10. Evaluation** | S5-101's Stage 4 PASS was a review error; keys unverified by an SME; diagnostic set concentrated on 820.10 | Stage 6 correction |

---

## 6. Model-capability analysis

**Are the remaining failures primarily capacity? Yes for the generated-answer failures; no for the system as a whole.**

**Likely capacity limitations** (a stronger model is expected to help) [Repo evidence / External expectation]:

| Limitation | Evidence |
|---|---|
| Dropped or misplaced qualifiers | AS-01 ("if applicable" moved to the wrong item), S5-010 ("as appropriate" dropped). Persists with exact evidence; fixing it by inlining conditions (h3) broke citations. **The model cannot hold both properties** |
| Multi-provision attribution | S5-101 (six similar fragments; text placed under a neighbour's number, 2–3 of 6 rows wrong), S5-012, S5-100 |
| Maintaining several requested elements | S5-006, AS-06 omit a keyed element present in the evidence |
| False-premise agreement | S5-053 ("Does (b)(2) require annual audits?" → "requires annual traceability audits") under every representation |
| Complex evidence instructions | list echo (S5-031 before Stage 6); requirement ids echoed ("r1:", "r2:") under a focused plan; degeneration on long lead-in provisions (S5-024) |
| Cross-source synthesis | synthesis citation gaps on S5-012, S5-021, S5-041, S5-100 persist with exact evidence (F16 in 7 questions) |

**Problems a larger model will not fix** [Repo]:

| Problem | Evidence |
|---|---|
| Retrieval misses | S5-061, S5-090; 56 % of the benchmark is general questions answered from full-text / OR-fallback retrieval |
| Wrong scope policy | S5-080, S5-082; a larger model will answer "capital of France" *more* fluently. This is a policy decision |
| Validator blind spots | S5-007, S5-101, uncited answers. A larger model makes fewer of these errors, but the ones it makes will be equally invisible |
| Database coverage | "not found in the available eCFR data" cases (S5-040–045; 25 "provision not found" refusals across the 379 diagnostic + benchmark questions) are correct behaviour, not model issues |
| Part-level evidence breadth | 112 of 300 benchmark questions ask about a whole Part; answering them well depends on selecting the right passages from dozens, a retrieval and selection problem first |

**Where model size stops being the bottleneck [Estimate].** On the diagnostic set:
* at best 11 of 18 failures are capacity (9 persistent plus 2 prompt-trade);
* if a larger model fixed all 11, the remaining 7 are retrieval, scope, validator and data;
* on the 300-question benchmark, retrieval is likely to become the bottleneck sooner, because most of its
  questions are general or part-level.

---

## 7. Model-swappability analysis

| Class | Components |
|---|---|
| **A: model-independent, no change** | the PostgreSQL database and `retrieval/*`; `planning/*`; `rag/coverage.py`; `rag/answerability.py`; `rag/fallback.py`; `rag/validation.py` and `shape_validation.py`; `rag/citations.py`; `rag/answer_quality.py`; `observability/*`; `evaluation/runner.py` ("knows nothing about Qwen"); `run_diagnostics.py` scoring; `generation_matrix.py`; `compare_runs.py`; `prompt_diff.py`; `web/index.html`; the dashboard (records the model id); the test suite (uses scripted generators) |
| **B: interface / configuration, small controlled change** | `configs/model.yaml` (id, device, dtype); `config/settings.py` default id; `rag/generator.py` (`QwenGenerator` and `load_qwen_generator` are generic HF in practice; rename or add a factory); `system_identity.configured_generation_config` (greedy; `enable_thinking` is a Qwen3 template kwarg that other templates ignore); scripts importing `load_qwen_generator` (`run_diagnostics.py`, `rag.py`, `serve_ui.py`, `generation_experiments.py`, `benchmark_latency.py`, `run_stage5.py`); `stage5/identity.py` (reads `describe()`); the fingerprint (records the model; no change) |
| **C: model-specific, needs adaptation or re-measurement** | **prompt layout** (`rag/answer_plan.py` plan lines placed early because 0.6B copies trailing lists; `rag/generation.py` system prompt and format lines). **Context policy** (`rag/context.py` sizes "small enough for a 0.6B model"; `rag/selection.py:required_only` and the Stage 6 conditions, all measured on 0.6B; a larger model may *benefit* from the related context 0.6B cannot use). **Token budget** (`GenerationBudget` constants, `CHARS_PER_TOKEN = 4.0` for the Qwen tokenizer; other tokenizers change budgets). **Streaming and timing** (`TextCallbackStreamer`, `_FirstTokenTimer` and `_finished` rely on transformers `generate` semantics and eos ids). `<think>` handling in `inference/chat.py` if thinking were ever enabled. Traces count context tokens with the loaded tokenizer |
| **D: hard coupling, refactor eventually** | **in-process transformers is the only backend**: no quantized runtime (MLX, llama.cpp/GGUF, AWQ/GPTQ), no remote serving (vLLM/TGI/OpenAI-compatible), single device. **Concurrency**: one process, one model, a global lock, no batching; production multi-user serving needs a serving layer behind the `Generator` protocol. **`finetune/*`** hard-codes `qwen3-0.6b-lora` paths and Qwen chat-template masking (training only) |

For **fair comparison** the class C items should be **held constant** across candidates in the first ladder
run: the same prompt text and the same context policy. They should be re-optimised per candidate only
afterwards, and reported separately.

---

## 8. Hardware and resource analysis

**Observed [Repo]:**
- **Machine:** Apple M2, 8 cores (4 performance + 4 efficiency), 10-core GPU (Metal 4), **8 GB unified memory**.
- **Software:** macOS 26.1; Python 3.11.9, PyTorch 2.14.0 (MPS yes, CUDA no), Transformers 5.17.0, PEFT 0.21.0,
  Accelerate 1.15.0. No MLX, llama.cpp, bitsandbytes or vLLM installed.
- **Disk:** 66 GB free of 228 GB.
- **Memory pressure during this audit**, with the UI and dashboard servers running: about 3.8 GB held in
  compressed form and 2.4 GB of 3 GB swap in use. **There is no memory headroom today.**

**Estimates:**
- *[Estimate]* weights ≈ parameters × bytes per parameter (bf16 = 2, 8-bit ≈ 1.05, 4-bit ≈ 0.55–0.6), plus
  KV cache and runtime.
- *[Estimate]* decode is memory-bound: tokens/s ≈ usable bandwidth ÷ weight bytes. The observed 0.6B MPS fp16
  figure is 28 tokens/s for about 1.2 GB of weights.
- *[External]* M2 memory bandwidth is about 100 GB/s.

| Model class | Weights bf16 / 4-bit [Estimate] | Local feasibility, this 8 GB M2 | Production feasibility [External + Estimate] |
|---|---:|---|---|
| 0.6B | 1.2 GB / — | **runs**, but swaps with the servers loaded | trivial; not quality-sufficient (§6) |
| 1.7B | 3.4 GB / ≈ 1.1 GB | bf16 on MPS marginal; 4-bit fits, but needs a new backend | cheap; unlikely to meet quality (§11) |
| 3–4B | 8 GB / ≈ 2.3–2.6 GB | **bf16 impossible**; 4-bit via MLX or llama.cpp only, with the DB and OS already at the limit. Development only | one 16–24 GB GPU (bf16), or CPU/Apple 4-bit; low cost |
| 7–8B | 16 GB / ≈ 4.5–5 GB | **not practical** (4-bit would displace PostgreSQL and the OS) | one 24 GB GPU bf16 (L4/A10G class), or a 16 GB GPU at 8-bit; moderate cost; mature serving |
| 12–14B | 28–30 GB / ≈ 8–9 GB | no | one 48 GB GPU bf16 (L40S/A6000 class), or 24 GB at 4-bit–8-bit; higher cost |
| 20B+ | 40+ GB / 11+ GB | no | 80 GB GPU bf16, or 48 GB at 8-bit |
| 30B+ (dense 32B; MoE e.g. 30B total / 3B active) | ≈ 60–64 GB / ≈ 17–19 GB | no | dense: 80 GB GPU or 2×48 GB; MoE: same memory as dense but decode speed of ≈ 3B active. Expensive; the reference role fits |

**Consequence [Repo + Estimate]:**
- Even the 4B quantized experiment on this laptop would work only with the servers stopped, and its latency
  would not represent production.
- **Candidates at 8B and above need other hardware**: a larger Apple machine (32–64 GB unified memory), or a
  rented or on-prem CUDA GPU.
- The evidence and prompts are public regulatory text, so running *evaluations* off-machine carries low data
  risk. Production deployment of client questions is a separate decision (§17).

---

## 9. Production constraints

**Repository facts [Repo]:**
- The README says that 0.6B is "a development choice, not the final production model". It names **Qwen3-4B, 8B,
  14B and 32B** as the production candidates: same family, tokenizer and chat template.
- The product must be **commercial and client-facing**: "Licence. Apache-2.0, suitable for commercial,
  client-facing use".
- The benchmark gates set the quality bar:
  * **G1** citation accuracy ≥ 0.99;
  * **G2** fabricated citations = 0;
  * **G3** negative controls = 100 %.
- Offline operation from a project-local model cache is designed in (`local_files_only`).
- The blueprint deferred quantization or a larger machine to "after correctness is measured"; that point has
  now been reached.

**Requirements a production model must meet**, derived from the above:

| Requirement | Why | Check at evaluation |
|---|---|---|
| Commercial use, redistribution and deployment rights (model **and** tokenizer license) | client-facing product | read each candidate's license file; Apache-2.0 or equivalent [External: the Qwen3 dense family is Apache-2.0; verify per checkpoint] |
| Standard HF causal LM, no `trust_remote_code` | loader design, security | load with the current loader |
| Quantization support (8-bit/4-bit) with a maintained runtime | local and low-cost serving | MLX / GGUF / AWQ availability [External] |
| Serving ecosystem (vLLM/TGI/llama.cpp, OpenAI-compatible) | concurrency (§7 D) | — |
| Fine-tuning support (LoRA/PEFT) | the only training path if needed later | PEFT compatibility |
| Context ≥ 8k tokens | prompts are ≤ about 2.6k today; part-level questions may grow | model card |
| Reliable instruction following and citation formatting | the validator depends on `[n]` markers | measured by the ladder |
| Deterministic greedy decoding | reproducibility, protected-pass checks | 10 repeats per candidate |
| Multilingual / tool calling | **not required today** (English 21 CFR; no tools) | note only |
| Security and updates | pinned revision and weight hash, as now | record like `f47f71177f32…` |

---

## 10. Candidate model-size strategy

**A. Minimum size likely capable of production-quality regulatory reasoning.**
- *Evidence [Repo]:* the failures are conditional logic, attribution among similar fragments, and false-premise
  resistance.
- *Hypothesis [Estimate]:* these typically improve markedly between about 3B and about 8B. **7–8B** is the
  realistic minimum for multi-provision and conditional answers; **4B** may suffice for single-provision lookups,
  which 0.6B already mostly handles.
- *Status:* this is a hypothesis for the ladder to test, not a conclusion.

**B. First serious production candidate: 7–8B** (e.g. Qwen3-8B, the same family as the baseline).
- It fits one 24 GB GPU in bf16, or a 16 GB GPU at 8-bit.
- Serving is mature, fine-tuning is feasible, and the tokenizer and chat template are identical, which keeps the
  comparison clean.

**C. Upper-bound / reference: one 30B-class model** (a dense ~32B, or a 30B-total / ~3B-active MoE of the same
family).
- It answers: "if even this fails a question, the cause is not model size."

**D. Where size stops being the bottleneck.**
- Once the ladder shows a rung that clears the 9 capacity failures (§6), the remaining failures are retrieval,
  scope, validator and data.
- Expect this at about 8–14B on the diagnostic set [Estimate]. It could come earlier on the benchmark, which is
  retrieval-heavy.

**E. One model or a ladder? A ladder.** A single model cannot show *where* the gains flatten, and cost and
latency rise steeply with size.

| Rung | Role |
|---|---|
| 1.7B | optional; free local slope point; not a candidate |
| 4B | smallest serious |
| 8B | candidate |
| 14B | reference; is 8B enough? |
| 30B-class | upper bound |

All rungs must run the same frozen evidence. **Do not** make 1.7B the next production step:
- the README already rules it out on the original hardware;
- the capacity failures are the kind small models share;
- a 1.7B pass would not remove the need to test 8B.

---

## 11. Evaluation methodology (proposed, not implemented)

1. **Freeze the evidence.**
   - For every question (79 diagnostic + 300 benchmark), store the Stage 6 pipeline's plan, gate decision,
     selected sources (texts and hashes), package and exact messages.
   - Every candidate receives **byte-identical messages**; only the chat template differs, and it is applied by
     each model's own tokenizer.
   - Gate-blocked questions stay blocked, so no model generates for them.
   - This extends `scripts/generation_experiments.py`, which already hashes prompts and caches outputs.
2. **Hold class C constant first.**
   - Use the same prompt and Stage 6 context policy, greedy decoding, thinking off.
   - Use the same token budget, computed once with the *baseline* tokenizer and passed as the cap; a large enough
     ceiling makes tokenizer differences irrelevant.
   - In a second, separately reported pass: the Stage 5 (full) context, because a larger model may use the
     related sources that 0.6B could not.
3. **Score identically.**
   - Same validator, repair and fallback, `diagnose.py`, keyed checks, and the protected-pass list.
   - Record raw, repaired and final text separately, as today.
4. **Harden scoring before trusting it** (Stage 7a; this audit does not change the validator):
   - a row-to-source attribution check;
   - detection of omitted or invented conditions;
   - an uncited-answer finding, as a separate metric;
   - applicability-overstatement detection.
   - Without these, the three error types found by developer review in Stage 6 would be invisible in the
     comparison.
5. **Metrics:**
   - *Quality:* final correctness (keyed + reviewed); unsupported claims (F07); qualifier retention (F08);
     citation correctness and completeness (F09 + attribution); enumeration completeness; provision attribution;
     multi-source synthesis (F16 condition); false-premise handling; safe-fallback behaviour (F13/F20).
   - *Reliability:* determinism (10 repeats); regression rate against 0.6B; protected-pass preservation; failure
     consistency across repeats.
   - *Performance:* first-token latency, total latency, tokens/s, prompt and generated tokens, peak memory, all
     on the target hardware.
   - *Economics:* GPU class; $/1k answers [Estimate from measured tokens/s × price]; concurrency (batching gain
     under vLLM); deployment complexity.
6. **Human review.**
   - Developer review of every changed answer (as in Stage 6).
   - **SME verification of the benchmark keys** before any production claim; the G1–G3 gates need it.
7. **Model-selection set.**
   - Keep the benchmark and `diagnostic_v1` protected and unchanged.
   - Create a *separate* model-selection set later, spread across parts, because 33 of 79 diagnostic questions
     are on 820.10.
   - Stratify it by question type: single, multi-provision, part-level, conditional, comparison, false premise,
     general.

---

## 12. Training / fine-tuning decision

**Decision: C, evaluate larger base models first, then decide on fine-tuning.** Rejected:

- **A (keep improving 0.6B):** Stage 6 exhausted representation changes. Every refinement traded one fix for
  one regression.
- **D (fine-tune 0.6B):** tried in Stages 12–14; it regressed (1 improved vs 13 regressed; reviewer mean 0.556
  vs 1.11), and one epoch takes 45.7 h here.
- **E (fine-tune a larger model now):** premature. The failure mode training should target is unknown until the
  base ladder shows what remains. Stage 13 shows that training data can teach a template instead of judgment.
- **B (move straight to one larger model):** replaced by the ladder (§10 E).
- **F (hybrid):** the system already *is* hybrid (deterministic gate, validation and repair around the model).
  Keep it. A second LLM (router or verifier) is not justified by the evidence yet.

---

## 13. Baseline to preserve (reproducible) [Repo]

| Item | Value |
|---|---|
| Model | `Qwen/Qwen3-0.6B` @ `c1899de289a0…`, weights sha256 `f47f71177f32…`, no adapter |
| Runtime | CPU float32 (`device: auto`, `dtype: auto`), greedy, thinking off, adaptive budget (min 256, ceiling 2,048) |
| Pipeline config | `answer_shape=adaptive`, `answerability=gate`, `optional_context=incomplete_only`, `validation_behavior=repair`; fingerprint version 4 |
| Diagnostic set | `diagnostic_v1.jsonl` sha256 `f99b1106aba8…`, 79 questions |
| Stage 5 (corrected) | reviewed PASS 44 / FAIL 17 / NEEDS_REVIEW 2 / UNVERIFIED 13 / UNVERIFIED_WITH_FAILURES 3 |
| Stage 6 (current) | reviewed PASS 46 / FAIL 15 / NEEDS_REVIEW 2 / UNVERIFIED 13 / UNVERIFIED_WITH_FAILURES 3 (automatic 47 / 14) |
| Protected Stage 4 PASS set | 39 questions, all PASS; S5-101's Stage 4 PASS was a review error (FAIL in all stages) |
| Latency (generated questions) | median 12.1 s, p90 49.8 s; first token median 1.68 s; prompt median 1,326 tokens |
| Determinism | 10/10 repeats identical |
| Known failures | §5 (18 + 2 NEEDS_REVIEW) |
| Tests | 1,185 passed, 1 skipped (default suite, run during this audit); 3 pre-existing slow-tier failures |
| Artifacts | `artifacts/diagnostics/stage6_result_final_20260930T040757Z` (with PROVENANCE, manual_review, comparison), `stage5_final_20260929T093254Z`, `stage4_rediagnosed_20260929T082457Z`; `artifacts/generation_quality/` |
| Integrity | benchmark `c009d5f9c649…`, `stage5_v1` `7cf80fda674f…`; DB read-only, `cfr_records` 65,341 |
| Version control | git repository `prachi-rp/regulus-ai` (private), commit `4396452` |

---

## 14. What we keep

- The regulatory database and the read-only access layer.
- Lexical retrieval and query planning (plan, intent, shape).
- The evidence registry, coverage and selection (Stage 6 policy kept as the default and re-measured).
- The answerability gate and safe fallback.
- Validation, repair and citations. Citations are built by the pipeline, never by the model.
- Streaming semantics (draft vs validated final) and the API/UI.
- Observability: traces, the failure taxonomy, diagnosis, raw-output preservation, the fingerprint.
- The evaluation framework: `run_diagnostics.py`, `generation_experiments.py`, `generation_matrix.py`,
  `compare_runs.py`, `prompt_diff.py`, the protected-pass comparison and the manual-review overlay.
- The benchmark and `diagnostic_v1` (protected, unchanged).
- The test suite, which uses scripted generators and is therefore model-independent.

## 15. What changes

Only genuinely model-specific components:

1. **Inference backend** (class D → a new `Generator` implementation behind the existing protocol):
   - a remote/OpenAI-compatible backend (vLLM/TGI/llama.cpp/MLX server);
   - optionally a quantized local backend;
   - the transformers backend stays.
2. **Generator factory and naming** (class B): select the backend and model by configuration; keep
   `QwenGenerator` for the baseline.
3. **Streaming and timing adapters** (class C) for server backends: token deltas, first-token time, finished or
   eos flag.
4. **Per-model re-measurement** (class C) of the prompt layout, context policy and token budget, *after* the
   like-for-like comparison.
5. **Serving and concurrency** (class D): batching and multiple workers once a production candidate is chosen.
   The global lock is fine for evaluation.

---

## 16. Recommended next engineering stage

**Stage 7 — Model Ladder Evaluation on Frozen Evidence.** No training; no change to retrieval, gate or
database. Its parts:

* **7a. Evaluation readiness** (measurement only; production answers unchanged):
  * the backend seam: a remote/OpenAI-compatible `Generator`, with a timing and streaming adapter;
  * a frozen-evidence export for the diagnostic set and the benchmark;
  * scorer hardening *as evaluation metrics*: attribution, conditions, uncited, overstatement. These are
    reported, not enforced;
  * a hardware decision for 8B+ (§17).
* **7b. Ladder run:**
  * 0.6B (re-run as control);
  * optional 1.7B;
  * 4B, 8B, 14B;
  * one 30B-class model.
  * Identical messages, greedy decoding, 10-repeat determinism, full metrics (§11).
* **7c. Decision report:**
  * the smallest rung that clears the capacity failures without regressions;
  * its latency and cost on the target hardware;
  * what remains, which is then the next stage's target: retrieval, scope policy, or enforced validator
    hardening.
  * Fine-tuning is reconsidered only for the chosen rung, and only against the failure mode that remains.

---

## 17. Risks

- **Hardware.** 8B+ cannot be evaluated on this machine; renting or buying hardware is a cost and procurement
  decision.
- **Scorer blind spots.** Without 7a, a larger model's fluent misattributions pass validation, and a candidate
  could look better or worse than it is.
- **Unverified keys.** Benchmark keys are unverified, so gate claims (G1–G3) cannot be certified until an SME
  reviews them.
- **Concentrated diagnostic set.** With 33 of 79 questions on 820.10, per-category conclusions for other parts
  are weak.
- **Tuned for 0.6B.** The prompt and context policy are optimised for 0.6B and may understate larger models;
  hence the second, separately reported pass.
- **Fluent scope answers.** Larger models answer out-of-scope and general-knowledge questions more convincingly;
  the scope policy question becomes more urgent, not less.
- **MPS vs CPU.** The two produce different text (5/60 in Stage 2); comparisons must hold the device constant, or
  report it.
- **Data leaving the machine.** Running evaluations off-machine sends regulatory text only; a production
  deployment would send client questions. That is a data-handling decision.

## Open questions

1. **Target production hardware:**
   - on-prem GPU server;
   - a cloud GPU (which region and provider is acceptable);
   - a larger Apple machine;
   - client-side deployment?
2. **Client data:** may client questions leave the client's environment? This decides local vs hosted serving.
3. **Latency and concurrency:** what are the targets, for example first token < 2 s and p90 total < 15 s at N
   concurrent users?
4. **Budget:** per 1,000 answers, or per month.
5. **SME:** who verifies the benchmark keys, and when?
6. **Scope policy for general-knowledge questions:** decline all, or answer with a caveat?
7. **Model families:** are families other than Qwen3 acceptable, subject to license review?

---

## Senior AI Architect Recommendation

* **Stay at 0.6B?** No, not for production. Keep it as the protected baseline and the control rung.
* **Evaluate 1.7B?** Only as an optional, free local data point for the scaling slope. It is not a candidate.
* **Skip 1.7B and evaluate larger models?** Yes. The failures are conditional logic, attribution among similar
  fragments, and premise resistance; those need more capacity than 1.7B is likely to have.
* **Size range first:** 4B → 8B as the candidate band, with 14B as the reference and one 30B-class model as the
  upper bound.
* **One model or a ladder?** A ladder, on identical frozen evidence, so the result shows where quality flattens
  against cost.
* **Train now?** No. Three LoRA attempts on 0.6B regressed. Decide on fine-tuning only for the chosen rung, and
  only against what it still fails.
* **Stage 7 should:**
  * add a pluggable inference backend and a frozen-evidence ladder harness;
  * add attribution, condition and uncited metrics;
  * choose evaluation hardware for 8B+;
  * then run 0.6B / 4B / 8B / 14B / 30B-class and report the smallest model that removes the capacity failures
    without regressions, with its latency and cost.

---

## Audit record

**Files inspected:**
- `configs/model.yaml`;
- `src/regulus/config/settings.py`;
- `src/regulus/model/{loader,device}.py`;
- `src/regulus/inference/{generate,chat,streaming,types}.py`;
- `src/regulus/rag/{generator,pipeline,generation,answer_plan,selection,context,answerability,fallback,validation}.py`;
- `src/regulus/system_identity.py`;
- `src/regulus/finetune/*` (references);
- `scripts/serve_ui.py`;
- `scripts/{run_diagnostics,generation_experiments}.py`;
- `data/evaluation/datasets/diagnostic_v1.jsonl`;
- the benchmark workbook, via `evaluation/acceptance_benchmark.py`;
- the model `config.json`;
- `README.md`.

**Reports inspected:**
- `docs/performance_baseline.md`, `streaming.md`, `mps_float16_evaluation.md`, `answer_quality.md`,
  `failure_observatory_stage4.md`, `answerability_gate_stage5.md`, `generation_quality_stage6.md`;
- `docs/stage0_architecture_blueprint.md`;
- `docs/stage12_model_training.md`, `stage13_grounding_and_training.md`, `stage14_overnight_training.md`,
  `stage6_training_design.md`;
- Stage 4–6 artifacts (diagnoses, traces, reviews, experiment summaries).

**Tests / status observed:** default suite 1,185 passed, 1 skipped; 3 pre-existing slow-tier failures (from the
Stage 6 run); UI and dashboard servers running.

**Hardware observed:** Apple M2, 8 GB unified memory, 10-core GPU (MPS), no CUDA, 66 GB free disk; memory
compressed about 3.8 GB, swap 2.4 of 3 GB used.
