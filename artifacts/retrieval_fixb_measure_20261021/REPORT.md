# Fix B measurement (read-only): result (2026-10-21)

**Result: F2 (8 rows per section, 16 rows total, the same 4 sections) is WORTH A CODE EXPERIMENT under the
pre-registered criteria. F1 (4 rows per section, 8 total) is CANDIDATES ONLY.**
- Nothing was implemented or enabled.
- Production code, prompts, configuration, database and indexes are unchanged. The context budget and ordering were
  untouched.
- No model or embedding model was run.
- **Database:** identity 65,280 / `4f0457d7…`, unchanged.
- **Semantic loader:** 0 attempts.
- **Pre-registration:** [PREREGISTRATION.md](PREREGISTRATION.md) `8e805f3c…`, tool `6334ffbb…`, locked at 17:06:55
  before the run ([LOCK.txt](LOCK.txt)).

## Method
- The production pipeline, with only the section-coverage SQL parameters varied in process
  ([tools/fixb_measure.py](tools/fixb_measure.py)).
- The same 4 top-ranked sections throughout.
- **100 cosmetics questions**, every condition.
- **352-row set:** F1 and F2 run here; base is the earlier production run `…16fa796d`, with identical code and
  database.
- **Check:** the harness base condition reproduces production exactly, 18 of 174 required paragraphs in context.

## Results ([evaluation.json](evaluation.json))

| | base (2 per section / 4 total) | F1 (4 / 8) | F2 (8 / 16) |
|---|---|---|---|
| Required paragraphs as **candidates** (100 Qs, general, of 174) | 22 | 29 (+7, −0) | **37 (+15, −0)** |
| Required paragraphs in **final context** | 18 | 19 (+1, −0) | **21 (+3, −0)** |
| New candidates reaching context | – | 1 of 7 (6 dropped at soft budget) | 3 of 15 (12 dropped at soft budget) |
| 352: keyed targets as candidates | – | +4, −0 | +6, −0 |
| 352: keyed targets in context (of 551) | 285 | 287 (+2, −0) | 288 (+3, −0) |
| 352: identifier / plain-language in context | 163 / 112 | – | 163 / 115 |
| Guidance passages removed (100 Qs) | – | 0 | 0 |
| eCFR rows removed (100 Qs) | – | 6, all non-required | 9, all non-required |
| B1 / B2 / B3 / B4 | – | **fail** / pass / pass / pass | pass / pass / pass / pass |

**Gains in final context (F2):**
- **100 cosmetics questions:**
  - COS-70.19-Q2: 70.19(i);
  - COS-74.2602a-Q1: 74.2602a(c), 74.2602a(e).
- **352 rows:**
  - L-004: 101.5;
  - L-016: 101.11;
  - Y-004: 108.35.
- **No losses.**

**New candidates that do not reach context (F2, all dropped at the soft budget):**
- COS-70.50-Q1: 70.50(a)
- COS-71.15-Q2: 71.15(c)
- COS-80.10-Q1: 80.10(c), 80.10(d)
- COS-82.1104-Q1: 70.3(v)
- COS-700.13-Q2: 700.13(d)
- COS-700.25-Q2: 700.25(d)
- COS-701.3-Q1: 701.3(a), 701.3(f)
- COS-701.3-Q4: 701.3(r)
- COS-720.4-Q3: 720.4(d)
- COS-740.12-Q1: 740.12(a)

**Displaced (F2, non-required eCFR rows):**
- COS-74.2052-Q1: 720.4(c)(6)(ii)
- COS-74.2203-Q1: 720.4(c)(3)(iii)
- COS-74.2327-Q1: 74.2052(c)
- COS-74.2340-Q1: 82.1051(b)
- COS-74.2602a-Q1: 81.30(i)
- COS-82.50-Q1: 82.1050, 82.2050, 82.6(a)
- COS-82.1206-Q1: 720.4(c)(6)

Their relevance was not judged. The pre-registration only required that no required paragraph be lost.

## Reading
- **Fix B does what the root cause predicted at candidate level.** Raising the per-section and total row caps makes
  15 more required paragraphs candidates on the cosmetics set (22 → 37), with no losses.
- **The current selection keeps only a fifth of them** (3 of 15). The other 12 come back as coverage rows, which sit
  behind every other piece of evidence and lose the 3,600-char soft budget. This matches what fixes A and D showed.
- **The final-context gain is small but clean.** +3 cosmetics paragraphs and +3 keyed targets on the 352 rows, with 0
  losses and no guidance removed.

## Smallest justified next step
**An authorized, default-off code experiment of F2.**
- **The change:** `SECTION_COVERAGE_ROWS_PER_SECTION` from 2 to 8, and the coverage row limit from 4 to 16, sections
  unchanged.
- **How it ships:** behind a switch, with a fresh pre-registration using the same criteria (B1–B4 plus the full test
  suite), on the same benchmarks.
- **Expected gains:** about +3 required paragraphs and +3 keyed targets, as measured here.

**Do not expect larger gains from Fix B alone.** 12 of the 15 recovered paragraphs are lost at selection. The two
ordering experiments (D, D2) showed that reordering cannot recover them without losing guidance or other keyed targets.
Any later attempt to keep them belongs to a separate, authorized selection study.
