"""Key recall in the prompt: does each 300Q question's expected CFR section reach the model's prompt? No model is run.

    python scripts/key_recall_eval.py run --record RECORDED.jsonl --out OUT.jsonl [--split dev|sealed|all] [--ids A,B]
    python scripts/key_recall_eval.py compare BASE.jsonl NEW.jsonl [--verdicts VERDICTS.json]

The production pipeline (retrieval_baseline.production_pipeline) runs every question up to its prompt. The section
picker - the one model call before the prompt is built - is replayed from RECORDED, a live run's answers.jsonl: when
the picker's candidate list equals the recorded one, decoding is greedy, so the recorded reply is the reply. A
question whose candidates changed is a "picker miss": nothing is promoted and the row says so (it needs a live run).
The answer itself is never generated: the stub captures the answer prompt and returns no text.

Per question it records the sources in the prompt, a hash of the answer prompt (an unchanged hash means an unchanged
answer - nothing to re-run live) and, for each section of the key's EXPECTED CITATION, the share of its text supplied:
whole (at least half), partial, absent. `complete` = every key section whole. The keys are the scoring keys of the
blind scorer (~/regulus_eval_runs/programme_20261026/scoring/keys.py), the database is only read, and the sealed
questions are left out unless --split sealed|all is asked for.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
KEYS = Path.home() / "regulus_eval_runs/programme_20261026/scoring"
SEALED = Path.home() / "regulus_eval_runs/programme_20261026/sets/acc300_sealed.json"
SELECTION = Path.home() / "regulus_eval_runs/cos50_20261027/sel_300.json"

SEC = re.compile(r"(?<![\d.])(\d{1,4})\.(\d{1,4}[a-z]?)(?![\d])")
RANGE = re.compile(r"(?<![\d.])(\d{1,4})\.(\d{1,4})\s*(?:-|–|through|to)\s*(?:\1\.)?(\d{1,4})(?![\d.])")
CAND = re.compile(r"^\[\d+\] (?:21 CFR (\S+)|FD&C Act § (\S+))", re.M)
WHOLE = 0.5


def key_sections(citation: str) -> list[str]:
    out = {f"{a}.{b}" for a, b in SEC.findall(citation or "")}
    for p, lo, hi in RANGE.findall(citation or ""):
        if 0 < int(hi) - int(lo) <= 12:
            out |= {f"{p}.{n}" for n in range(int(lo), int(hi) + 1)}
    return sorted(out)


class ReplayGenerator:
    """The picker's recorded reply when its candidates match the recording; the answer call is captured, not run."""

    def __init__(self, picker_system: str, live=None, retrieval_systems: tuple[str, ...] = ()) -> None:
        self.picker_system = picker_system
        self.retrieval_systems = retrieval_systems   # other retrieval-stage model calls (NAV1, QD1, QX1): asked live
        self.live = live   # the MLX model (behind a reply cache) for a picker call the recording cannot replay
        self.recorded: dict | None = None
        self.picker = "none"
        self.prompt_sha: str | None = None

    def generate(self, messages, max_new_tokens=None, on_text=None, **kw):
        from regulus.inference.types import GenerationResult

        text = ""
        if messages and messages[0].get("content") == self.picker_system:
            cands = [a or b for a, b in CAND.findall(messages[-1]["content"])]
            rec = self.recorded or {}
            if cands and cands == list(rec.get("candidates") or []):
                text, self.picker = rec.get("picker_output") or "", "replayed"
            elif self.live is not None:
                text, self.picker = (self.live.generate(messages, max_new_tokens=max_new_tokens, **kw).response or ""), "live"
            else:
                self.picker = "miss"
        elif messages and messages[0].get("content") in self.retrieval_systems:
            text = (self.live.generate(messages, max_new_tokens=max_new_tokens, **kw).response or "") if self.live else ""
        elif self.prompt_sha is None:
            self.prompt_sha = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]
        return GenerationResult(prompt="", response=text, prompt_tokens=0, generated_tokens=0, seconds=0.0, finished=True)

    def describe(self) -> dict:
        return {"model_id": "none (key recall: the picker is replayed, the answer is never generated)"}


def cmd_run(a) -> None:
    sys.path.insert(0, str(KEYS))
    from keys import load_keys
    from regulus.evaluation import retrieval_baseline as RB
    from regulus.rag.section_promotion import EXPANSION_SYSTEM, NAV1_SYSTEM, PICKER_SYSTEM, QD1_SYSTEM
    from regulus.retrieval import Database

    keys = load_keys()
    recorded = {}
    for line in Path(a.record).read_text().splitlines():
        r = json.loads(line) if line.strip() else {}
        if r.get("id") and not r.get("error"):
            recorded[r["id"]] = r
    sealed = {q["ID"] for q in json.load(SEALED.open())["questions"]}
    sel = json.load(SELECTION.open())
    text_of = {q["ID"]: q.get("Question (ask verbatim)") or q.get("question") for q in sel["questions"]}
    ids = [i for i in sel["summary"]["selected_ids"] if a.split == "all" or (i in sealed) == (a.split == "sealed")]
    if a.ids:
        keep = set(a.ids.split(","))
        ids = [i for i in ids if i in keep]

    db = Database.from_env()
    db.connect()
    guarded = db.query

    def read_only(sql, params=None, *x, **k):
        if sql.lstrip().split(None, 1)[0].upper() not in ("SELECT", "WITH"):
            raise RuntimeError("key recall is read-only")
        return guarded(sql, params, *x, **k)

    db.query = read_only
    pipe, _ = RB.production_pipeline(db)
    live = None
    if a.mlx:
        sys.path.insert(0, str(ROOT / "scripts"))
        from section_resolution_eval import CachedGenerator, _mlx_generator

        live = CachedGenerator(_mlx_generator(), Path(a.cache))
    # every retrieval-stage model call is asked (behind the reply cache), never taken for the answer call: QD1's
    # sub-question call read as the answer used to get "" - decomposition did nothing and set the prompt fingerprint
    gen = ReplayGenerator(PICKER_SYSTEM, live, (NAV1_SYSTEM, QD1_SYSTEM, EXPANSION_SYSTEM))
    pipe.generator = gen
    need = sorted({s for i in ids for s in key_sections(keys[i].get("citation") or "")})
    size = {r["section_number"]: int(r["n"]) for r in db.query(
        "SELECT section_number, sum(length(body_text)) n FROM cfr_records WHERE removed_on IS NULL AND NOT is_reserved "
        "AND section_number = ANY(%(s)s) GROUP BY 1", {"s": need})}
    t0 = time.perf_counter()
    with Path(a.out).open("w", encoding="utf-8") as f:
        for n, qid in enumerate(ids, 1):
            gen.recorded = (recorded.get(qid) or {}).get("promotion")
            gen.picker, gen.prompt_sha = "none", None
            fallback = None
            try:
                r = pipe.answer(text_of[qid])
                sources = [[x.result.citation.label, x.tier, len(x.text or "")] for x in r.context.sources]
                promo, err, fallback = r.metadata.get("section_promotion") or {}, None, r.metadata.get("fallback_type")
            except Exception as exc:  # noqa: BLE001 - one failing question is recorded, not fatal
                sources, promo, err = [], {}, f"{type(exc).__name__}: {exc}"[:300]
            promoter = pipe.__dict__.get("_promoter")
            scores = {s: round(v[0], 4) for s, v in ((promoter.__dict__.get("last_rerank") if promoter else None) or {}).items()}
            if promoter is not None:
                promoter.__dict__.pop("last_rerank", None)
            # composed answers make no model call: the sources and the answer path are part of what the user is shown
            fingerprint = hashlib.sha256(json.dumps([gen.prompt_sha, sources, fallback]).encode()).hexdigest()[:16]
            got = collections.Counter()
            for label, _, chars in sources:
                for s in {f"{p}.{q}" for p, q in SEC.findall(label)}:
                    got[s] += chars
            req = [s for s in key_sections(keys[qid].get("citation") or "") if s in size]
            status = {s: ("whole" if got[s] / size[s] >= WHOLE else "partial" if got[s] else "absent") for s in req}
            f.write(json.dumps({
                "id": qid, "split": "sealed" if qid in sealed else "dev", "required": req, "status": status,
                "complete": bool(req) and all(v == "whole" for v in status.values()),
                "recall": round(sum(v == "whole" for v in status.values()) / len(req), 3) if req else None,
                "picker": gen.picker, "prompt_sha": fingerprint, "fallback": fallback, "prompt_chars": sum(c for _, _, c in sources),
                "promoted": promo.get("sections"), "companions": promo.get("companions"), "notes": promo.get("notes"),
                "candidates": promo.get("candidates"), "rerank": scores, "sources": sources, "error": err}) + "\n")
            if n % 25 == 0:
                print(f"{n}/{len(ids)} {time.perf_counter() - t0:.0f} s", flush=True)
    db.close()
    if live is not None:
        print(f"picker calls: {live.fresh} on the model, {live.cached} from the cache")
        live.real.close()
    summary(a.out)


def _load(path) -> dict:
    return {r["id"]: r for r in (json.loads(l) for l in Path(path).read_text().splitlines() if l.strip())}


def summary(path) -> None:
    rows = list(_load(path).values())
    keyed = [r for r in rows if r["required"]]
    print(f"{path}: {len(rows)} questions, {len(keyed)} with a CFR key | complete {sum(r['complete'] for r in keyed)} | "
          f"mean recall {sum(r['recall'] for r in keyed) / max(len(keyed), 1):.3f} | picker "
          f"{dict(collections.Counter(r['picker'] for r in rows))} | errors {sum(bool(r['error']) for r in rows)}")


def cmd_compare(a) -> None:
    base, new = _load(a.base), _load(a.new)
    cat = {}
    if a.verdicts:
        v = json.loads(Path(a.verdicts).read_text())
        cat = {k: x["cat"] for k, x in (next(iter(v.values())) if "D-011" not in v else v).items()}
    both = [i for i in base if i in new]
    changed = [i for i in both if base[i]["prompt_sha"] != new[i]["prompt_sha"]]
    gained = [i for i in both if new[i]["complete"] and not base[i]["complete"]]
    lost = [i for i in both if base[i]["complete"] and not new[i]["complete"]]
    up = [i for i in both if (new[i]["recall"] or 0) > (base[i]["recall"] or 0)]
    down = [i for i in both if (new[i]["recall"] or 0) < (base[i]["recall"] or 0)]
    for name, ids in (("prompt changed (re-run live)", changed), ("became complete", gained), ("lost complete", lost),
                      ("recall up", up), ("recall down", down)):
        print(f"{name:30} {len(ids):4}  {', '.join(f'{i}({cat.get(i, chr(63))[:4]})' for i in ids[:40])}")
    risk = [i for i in changed if cat.get(i) == "PASS"]
    print(f"{'PASS answers whose prompt changed':30} {len(risk):4}  {', '.join(risk)}")
    print("picker misses in NEW:", sum(new[i]["picker"] == "miss" for i in both))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--record", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--split", default="dev", choices=["dev", "sealed", "all"])
    r.add_argument("--ids")
    r.add_argument("--mlx", action="store_true", help="call the MLX model for picker prompts the recording cannot replay")
    r.add_argument("--cache", default=str(Path.home() / "regulus_eval_runs/cos50_20261027/picker_cache.jsonl"))
    c = sub.add_parser("compare")
    c.add_argument("base")
    c.add_argument("new")
    c.add_argument("--verdicts")
    a = p.parse_args()
    cmd_run(a) if a.cmd == "run" else cmd_compare(a)


if __name__ == "__main__":
    main()
