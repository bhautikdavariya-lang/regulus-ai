# Results: per-part evidence extraction diagnostic (Qwen3-1.7B MLX 4-bit, 2026-10-22)

Pre-registration: PREREGISTRATION.md (sha256 90c3c295...), set diag_set.json (cd75d642...), locked before the run.
Outputs: outputs.jsonl (28 calls, prompts included); mechanical verbatim check: verbatim_check.json.

## Judgements (scorer = the benchmark scorer, against the verified key)

| Group | HIT (>=1 useful quote, no wrong one) | FALSE ANSWER (any wrong/misleading or non-verbatim quote) | Correct NOT IN SOURCES only |
|---|---:|---:|---:|
| A: key section in evidence (13) | 4 strict / 5 lenient* | 8 | 0 |
| C1: key not in evidence (12) | - | 12 | 0 |
| C2: statute-only (3) | - | 2 | 1 (UC-COS-011) |

*Lenient counts COS-701.3-Q4, whose 701.3(m) quote differs from the source only in quote characters.

HIT: COS-74.2052-Q1 (74.2052(c) list), COS-80.31-Q1 (80.31(a)(3) only), COS-82.6-Q1 (82.6(a) lead-in only),
COS-740.12-Q1 (740.12(b) caution), lenient COS-701.3-Q4.

Wrong or misleading quotes in group A, examples:
- COS-700.18-Q1: quotes only the first sentence of 700.18(b) ("...adulterated"), omitting the residue exclusion that
  makes the key's answer "not on the residue alone" - the extraction reverses the correct answer.
- COS-720.4-Q3: quotes the first sentence of 720.4(e) without the hair-dye exception, plus an NDA guidance sentence.
- COS-700.15-Q1 (infant formula guidance), COS-701.13-G1 (drug tablet guidance), COS-700.13-Q2 (non-verbatim VQIP
  lines), COS-700.14-Q1 (drug rule 310.502), COS-80.10-Q1 (repack fee paragraph), COS-740.11-Q2 (warning attributed to
  OTC drug rule 369.21).

Controls: 14 of 15 produced "evidence" for a question their sources cannot answer, e.g. 21 CFR 1271.90 HCT/P donor
labeling quoted as the restrictions for caramel, ferric ammonium ferrocyanide and copper powder (several quotes not
verbatim); food-label declaration guidance quoted for a lip balm; a food-facility registration FAQ quoted for FD&C 607
suspension; food additive petition confidentiality (171.1) quoted for a cosmetic Form 2512 trade-secret request.

Non-verbatim (fabricated or altered) quotes: 15 lines across 9 questions.

## Verdict (pre-registered rule): CAPABILITY LIMIT - NOT WORTH IMPLEMENTING
A hits 4-5/13 (< 7 required; <= 3 would be the hard floor), control false answers 14/15 (>= 3 is the failure line),
fabricated quotes 15 (0 required).

## What this establishes
- The 1.7B model does not discriminate relevant from irrelevant evidence. Asked to extract rather than answer, it
  assigns whatever text is present to the question's parts, including clearly off-topic provisions.
- Its bare declines on general questions are therefore protective in the current system: in the 22 Oct run 80 declines
  produced 1 invented requirement, against 18 on 0.6B. A change that makes this model answer more often from the same
  evidence would deliver grounded-looking wrong answers.
- Together with the 21 Oct oracle (0/8 general questions answered with verified evidence) and eight refuted prompt or
  thinking variants, this places the general-question answer failure in model capability, not prompt wording.
