# Performance baseline (2026-09-29)

Measured before any optimisation. Nothing about answers was changed: three
recorded answers were regenerated after instrumentation and are byte-identical
(same token counts). Raw data: `artifacts/latency/baseline_20260929T040232Z/`.

## How it was measured

* `python scripts/benchmark_latency.py`: the configured production pipeline
  (same settings as the answering UI: greedy, thinking off, validation
  `repair`) on 15 existing Stage 5 questions covering every path (single,
  parent, section, multi, range, partial, not found, general, guidance,
  out-of-domain, long). The first question after model load is reported as
  "cold"; the statistics below are the 13 warm questions that called the model.
  CPU and memory sampled every 0.5 s with psutil.
* HTTP: `scripts/serve_ui.py` with `curl`, three questions.
* UI: the page's own `render()` run under Node on three real responses.
* Machine state: quiet (VS Code and Chrome open; answering UI and dashboard stopped).

## Stage latencies (warm, model called, n = 13)

| Stage | Median | p90 | Max | Where measured |
|---|---:|---:|---:|---|
| Request handling (parse, lock, setup, JSON serialise + send) | < 1 ms | < 1 ms | 0.6 ms | `server_timings_ms`, server log |
| Retrieval (incl. question planning 0.1 ms) | 21 ms | 1,086 ms | 1,949 ms | `timings_ms.retrieval_ms` |
| Reranking | — | — | — | none exists (scores are merged inside retrieval) |
| Context construction (coverage + selection + package + prompt + tokenise) | 5 ms | 13 ms | 22 ms | `context_ms + package_ms + prompt_ms + model_prepare_ms` |
| Model first token (prefill + first step) | 1.84 s | 2.77 s | 2.84 s | `model_first_token_ms` |
| Model generation (decode, after first token) | 8.04 s | 18.40 s | 43.29 s | `model_decode_ms` |
| Post-processing (detokenise, validate, repair, citations, diagnostics) | 1.3 ms | 5 ms | 7 ms | `validation_ms + citations_ms + metadata_ms + model_detokenize_ms` |
| UI rendering (page JavaScript) | 0.2–0.4 ms | — | 2.8 ms | Node, 50 runs × 3 responses |
| **Total (server)** | **10.3 s** | **21.3 s** | **45.3 s** | `total_ms` |

* **Time to first visible output = total time.** Nothing is streamed: HTTP
  time-to-first-byte equalled total time (8.07 s / 8.07 s, 20.84 / 20.84,
  9.48 / 9.48).
* The first question after a model load took 8.7 s, including a cold
  retrieval (424 ms, of which 337 ms is the first exact-CFR SQL).
* Not measured: browser HTML parse and layout of the 40–90 KB the page inserts
  (most of it the raw-JSON panel). The page now prints its own request, parse
  and render time in the status line, so it can be read in a real browser.

## System facts

| | |
|---|---|
| Model | Qwen/Qwen3-0.6B, base, no adapter |
| Model size | 596 M parameters; 2,274 MB in memory (float32) |
| Device / dtype | **CPU, float32**, 4 torch threads (`device: auto` only knows CUDA and CPU) |
| Hardware | Apple M2 (4 performance + 4 efficiency cores), macOS 26.1 |
| RAM | 8 GB unified; process RSS 2.9–3.5 GB; up to 1.15 GB swap in use, lowest free memory 1.3 GB |
| GPU / VRAM | Apple M2 10-core GPU (Metal / PyTorch MPS available), **unused**; shares the 8 GB |
| Context window | 40,960 tokens; prompts used 691–2,087 (median 1,372) |
| Retrieved context | median 4 sources (1–12), median 3,470 characters |
| Model load time | 2.2–3.9 s (weights in page cache) |
| Average answer length | mean 137 tokens, median 107 (11–487) |
| Tokens/second | decode median 13.2 (10.3–14.6); overall including prefill 10.2; prefill ≈ 775 prompt tokens/s |
| CPU utilisation | process mean 175 % (≈ 1.75 of 8 cores); whole system ≈ 28 % |
| Streaming | backend: no (only the non-RAG `scripts/chat.py` prints tokens); frontend: no (`await res.json()`) |

The earlier documented 1.86 tokens/s (`answer_length_policy.md`) was measured
while the machine was swapping; on a quiet machine decode is about 7× faster.

## Streaming: current capability

* `generate_chat()` already accepts a transformers streamer (`scripts/chat.py`
  uses `TextStreamer` for the terminal). `QwenGenerator.generate()`,
  `RagPipeline.answer()` and `serve_ui.py` do not pass one on.
* `serve_ui.py` is a stdlib `BaseHTTPRequestHandler` returning one JSON body
  with `Content-Length`; `web/index.html` reads it with `await res.json()` and
  renders once. Browsers can read a streamed `fetch` body, so the page could
  consume one with changes; the server cannot produce one today.
* Design constraint for later: validation and repair run *after* generation
  and can replace or extend the answer (extractive replacement, appended
  items). Streamed raw text would therefore need a final "validated answer"
  event that may differ from what was streamed.

## Device probe (measurement only, nothing in the project changed)

Same three prompts, same greedy decoding, different device and precision.

| Device / dtype | First token | Decode tokens/s | Total (3 answers) | Same text as current (CPU fp32) |
|---|---:|---:|---:|---|
| CPU float32 (current) | 2.0–2.8 s | 10.1–12.6 | 67.2 s | 3/3 (reference) |
| CPU bfloat16 | 25–39 s | 17.6–20.5 | 130.5 s | **1/3**: rejected |
| M2 GPU (MPS) float32 | 1.2–1.7 s | 16.4–17.8 | 45.9 s | 3/3 |
| **M2 GPU (MPS) float16** | **1.0–1.3 s** | **27.1–28.2** | **29.2 s** | **3/3** |

MPS first-token times include one decode step (transformers streams one step
late on MPS). Three identical answers are encouraging, not proof: a device or
precision change must be validated on the full benchmark before adoption.

## Answers

**1. What is slow?** Token generation. Decode is 78 % of the median answer
(8.0 of 10.3 s) and all of the long tail (43 s for a 487-token answer). Prefill
(first token) is the next 18 % (1.8 s). Retrieval is fast (median 21 ms)
except for general and guidance questions, where the FDA-guidance full-text
query takes 0.3–1.8 s. Everything else together is under 30 ms. And because
nothing is streamed, the user waits the whole time with nothing on screen.

**2. Why is it slow?** The model runs in float32 on the CPU, so every
generated token reads all 2.3 GB of weights. At 13 tokens/s that is about
30 GB/s, the memory-bandwidth limit of CPU inference on this machine, not a
compute limit (the process uses about 1.75 of 8 cores). The Apple GPU, which
handles exactly this workload, is unused because the device resolver only
recognises CUDA. With 8 GB shared by the OS, VS Code, Chrome and a 3.3 GB
process, the machine swaps; when it does, speed collapses (the 1.86 tokens/s
measured earlier).

**3. What should be optimised first?**
1. **Streaming the answer.** It doesn't make the answer faster, but it cuts
   time-to-first-visible-text from about 10 s to 1–2 s for every question. It
   needs a design for the post-generation validation and repair described
   above.
2. **Run the model on the M2 GPU in float16** (behind a config switch, the
   current path kept): 2.2–2.5× faster end to end (2.8× on decode) and half the memory
   (1.1 GB of weights instead of 2.3 GB), with identical answers on 3/3
   probes. Must be validated on the full benchmark first.
3. **The guidance full-text query** (0.3–1.9 s on general/guidance
   questions): check its plan and indexes; no change to what it returns.

**4. What hardware is actually required?** None beyond this Mac for this
model. Measured: the M2's own GPU gives about 28 tokens/s and about 1 s to
first token. That would put the median answer at roughly 4–5 s and the
487-token worst case at about 18 s. The real constraint is 8 GB of RAM: it
caused swap here and caused the 7× slowdown seen earlier. 16 GB would remove
that risk. A discrete NVIDIA GPU would be far faster still, but a 0.6B model
needs about 1.2 GB of memory in float16, so it isn't needed unless the model
grows.

**5. What can be improved in software, without new hardware?**
* Streaming (perceived latency: about 10 s → 1–2 s).
* Apple GPU + float16 (measured 2.2–2.5× end to end; requires full-benchmark validation).
* Keeping memory free while serving (the UI already loads one model; avoid a
  second process holding another copy): prevents the swap collapse.
* The guidance full-text SQL (up to 1.9 s).
* Smaller levers, measure before doing: caching the fixed system-prompt prefix
  (prefill), torch thread count on CPU.
* Not recommended: CPU bfloat16 (it changed 2 of 3 answers and made prefill
  12× slower); cutting retrieved context to save prefill (it would trade
  answer quality for about 1 s).
