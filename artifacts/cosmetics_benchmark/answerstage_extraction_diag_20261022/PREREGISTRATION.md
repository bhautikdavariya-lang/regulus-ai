# Answer-stage diagnostic: per-part evidence extraction on Qwen3-1.7B (2026-10-22)

Written before any output was generated.

## Question
In the 22 Oct 1.7B cosmetics run, 13 questions were answered with the bare decline although the prompt carried the
key's section, mostly as answer-bearing rows (e.g. 74.2052(c), 80.10(a), 82.6(a)(3), 700.18(b), 720.4(e),
740.12(b)). Prompt-wording variants of the answer prompt (V1/V2/V3/S1/S2/GQ/VT/VR3, format line, thinking mode) did
not reduce declines on 1.7B (records of 20-21 Oct). This tests a different task, not a reworded answer prompt: ask the
model to split the question into its parts and copy, for each part, the source sentence that answers it, or write
NOT IN SOURCES.

## Set (diag_set.json, chosen mechanically before the run)
- A: the 13 class-A declines (key section in evidence).
- C1: 12 plain declines whose key section was NOT in evidence (every 4th in run order) - negative controls.
- C2: 3 statute-only questions (FD&C Act key, no statute in corpus) - negative controls.

## Fixed inputs
The exact source texts and order the 22 Oct prompt carried (responses/<ID>.json `sources`), same model
(Qwen3-1.7B MLX 4-bit 21457c6f, greedy, thinking off), same chat template. One call per question. The app's memory
preflight is called with 1,200 MB for this offline harness only (production unchanged; no timings are measured).

## Scoring (by the same scorer as the benchmark, against the verified key)
Per question, each extracted EVIDENCE line is checked mechanically for verbatim presence in the cited source
(whitespace-normalised), then judged:
- USEFUL: verbatim, and states a key answer element for the part it is assigned to.
- WRONG: verbatim or not, assigned to a part it does not answer (would mislead), or not verbatim (fabricated quote).
A question is a HIT if it has >= 1 USEFUL line and no WRONG line; a FALSE ANSWER if it has any WRONG line.

## Pre-registered thresholds
- Promising (worth implementing behind a switch and a full-benchmark run): A hits >= 7/13 AND false answers in
  C1+C2 <= 1/15 AND fabricated (non-verbatim) quotes = 0 overall.
- Capability limit / not worth implementing: A hits <= 3/13, or false answers in controls >= 3/15.
- Otherwise inconclusive: do not implement.
