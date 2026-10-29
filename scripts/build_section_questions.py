"""Index-time question generation (doc2query / hypothetical-question indexing) for the section candidate list - step D.

For each live section of the given parts the MLX model writes the plain-language questions the section answers; a user's
question is later matched against them (regulus.retrieval.section_questions). A question worded as users word it finds
a section its legal text does not: 300Q full300c, 19 answers never had their key section among the candidates.

    python scripts/build_section_questions.py --parts 117,111 [--limit N] [--out FILE] [--cache FILE]
    python scripts/build_section_questions.py --key-parts            # the parts the 300Q keys cite (55 parts, 1,625 sections)

Resumable: sections already in OUT are skipped. Every model call goes through the reply cache. Each reply is checked:
3-5 questions, each ending in "?", none naming a section, part or paragraph number - a section whose reply fails is
written with no questions and the reason, never with unchecked text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "data" / "processed" / "section_questions" / "questions.jsonl"
CACHE = Path.home() / "regulus_eval_runs" / "section_questions_cache.jsonl"
DOC_CHARS = 2400
MAX_TOKENS = 200
SYSTEM = ("You write the questions people working in U.S. FDA regulatory compliance ask that a regulation section answers. "
          "Use the plain words such a person would use, not the regulation's own phrasing where a plainer word exists.")
INSTRUCTION = ("Write four different questions that the section above answers, one per line. Each question must be "
               "answerable from this section alone. Do not mention section, part or paragraph numbers, and do not say "
               "'this section'. Output only the questions.")
_NUMBERED = re.compile(r"^\s*(?:[-*•]|\(?\d{1,2}[.)])\s*")
_NAMES_PROVISION = re.compile(r"\b\d+\.\d+\b|§|\b(?:this|the)\s+(?:section|regulation|paragraph|part)\b|\bpart\s+\d+", re.I)

_SECTIONS_SQL = """
SELECT section_number, min(part_number) AS part, min(section_heading) AS heading,
       string_agg(body_text, ' ' ORDER BY ordinal) AS text
FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved AND part_number = ANY(%(p)s)
GROUP BY section_number ORDER BY min(part_number), section_number
"""


def parse_questions(reply: str) -> tuple[list[str], str | None]:
    """(questions, None) when the reply holds 3-5 usable questions, else ([], reason)."""
    out = []
    for line in (reply or "").splitlines():
        q = _NUMBERED.sub("", line).strip().strip('"')
        if not q:
            continue
        if not q.endswith("?"):
            return [], f"not a question: {q[:60]!r}"
        if _NAMES_PROVISION.search(q):
            return [], f"names a provision: {q[:60]!r}"
        if q not in out:
            out.append(q)
    if not 3 <= len(out) <= 5:
        return [], f"{len(out)} questions"
    return out, None


def messages(heading: str, text: str) -> list[dict]:
    doc = " ".join((text or "").split())[:DOC_CHARS]
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"SECTION: {heading}\n{doc}\n\n{INSTRUCTION}"}]


def key_parts() -> list[str]:
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("--key-parts reads the benchmark workbook and needs openpyxl; or name the parts with --parts")

    wb = next(ROOT.glob("Regulus_AI_Acceptance_Benchmark_REV02_300Q.xlsx"))
    parts: set[str] = set()
    for row in openpyxl.load_workbook(wb, read_only=True, data_only=True)["Question Bank"].iter_rows(values_only=True):
        text = " ".join(str(c) for c in row if c)
        parts |= set(re.findall(r"(?<![\d.])(\d{1,4})\.\d", text)) | set(re.findall(r"\bPart\s+(\d{1,4})\b", text, re.I))
    return sorted((p for p in parts if int(p) > 0), key=int)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", help="comma-separated part numbers")
    ap.add_argument("--key-parts", action="store_true", help="the parts the 300Q benchmark keys cite")
    ap.add_argument("--limit", type=int, help="at most this many new sections (a sample)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--cache", default=str(CACHE))
    a = ap.parse_args()
    parts = key_parts() if a.key_parts else [p.strip() for p in (a.parts or "").split(",") if p.strip()]
    if not parts:
        raise SystemExit("name --parts or --key-parts")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["section"] for l in out.read_text(encoding="utf-8").splitlines() if l.strip()} if out.exists() else set()

    from regulus.evaluation.reply_cache import CachedGenerator
    from regulus.retrieval import Database

    sys.path.insert(0, str(ROOT / "scripts"))
    from section_resolution_eval import _mlx_generator

    db = Database.from_env()
    db.connect()
    todo = [r for r in db.query(_SECTIONS_SQL, {"p": parts}) if r["section_number"] not in done]
    db.close()
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(parts)} parts; {len(done)} sections already done; {len(todo)} to go", flush=True)
    if not todo:
        return 0
    gen = CachedGenerator(_mlx_generator(), Path(a.cache))
    model = (gen.describe() or {}).get("model_id")
    t0 = time.perf_counter()
    try:
        with out.open("a", encoding="utf-8") as f:
            for n, r in enumerate(todo, 1):
                reply = gen.generate(messages(r["heading"] or "", r["text"] or ""), max_new_tokens=MAX_TOKENS).response
                questions, why = parse_questions(reply)
                f.write(json.dumps({"section": r["section_number"], "part": r["part"], "heading": r["heading"],
                                    "questions": questions, "rejected": why, "model": model,
                                    "text_sha": hashlib.sha256((r["text"] or "").encode()).hexdigest()[:16]}) + "\n")
                f.flush()
                if n % 10 == 0 or n == len(todo):
                    left = (time.perf_counter() - t0) / n * (len(todo) - n)
                    print(f"[{n}/{len(todo)}] {r['section_number']} {'ok' if questions else why}  ~{left / 60:.0f} min left",
                          flush=True)
    finally:
        gen.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
