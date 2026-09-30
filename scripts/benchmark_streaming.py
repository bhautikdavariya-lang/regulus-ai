"""Streaming vs. non-streaming, measured from the client, against a running answering UI.

    python scripts/serve_ui.py --offline          # in another terminal
    python scripts/benchmark_streaming.py

For each question: POST /api/ask (non-streaming) and POST /api/ask/stream,
one after the other on the same server (greedy decoding, so both generate the
same text). Reports time to first byte, time to first streamed text, number
of text chunks, time to the final validated answer, total generation time,
and whether the final streamed answer equals the non-streaming one.
Output: artifacts/latency/streaming_<utc>/. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "evaluation" / "datasets" / "stage5_v1.jsonl"
DEFAULT_IDS = ("S5-001", "S5-012", "S5-024", "S5-043", "S5-060", "S5-070", "S5-100")


def post(base: str, path: str, question: str):
    req = urllib.request.Request(base + path, data=json.dumps({"question": question}).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=1800)


def non_streaming(base: str, question: str) -> dict:
    t0 = time.perf_counter()
    with post(base, "/api/ask", question) as res:
        first_byte = time.perf_counter()
        body = json.loads(res.read())
    t1 = time.perf_counter()
    return {"ttfb_ms": round((first_byte - t0) * 1000, 1), "total_ms": round((t1 - t0) * 1000, 1), "result": body}


def streaming(base: str, question: str) -> dict:
    t0 = time.perf_counter()
    first_text = first_byte = None
    chunks = 0
    final = error = None
    with post(base, "/api/ask/stream", question) as res:
        for raw in res:  # one event per line, read as it arrives
            if first_byte is None:
                first_byte = time.perf_counter()
            if not raw.strip():
                continue
            ev = json.loads(raw)
            if ev["type"] == "delta":
                chunks += 1
                if first_text is None:
                    first_text = time.perf_counter()
            elif ev["type"] == "final":
                final = ev["result"]
            elif ev["type"] == "error":
                error = ev["error"]
    t1 = time.perf_counter()
    ms = lambda t: round((t - t0) * 1000, 1) if t is not None else None
    return {"ttfb_ms": ms(first_byte), "first_text_ms": ms(first_text), "chunks": chunks, "total_ms": ms(t1),
            "result": final, "error": error}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--ids", nargs="*", default=list(DEFAULT_IDS))
    args = p.parse_args()
    items = {json.loads(l)["id"]: json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()}
    out_dir = ROOT / "artifacts" / "latency" / f"streaming_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for qid in args.ids:
        q = items[qid]["question"]
        plain = non_streaming(args.base, q)
        stream = streaming(args.base, q)
        pr, sr = plain["result"], stream["result"] or {}
        row = {
            "id": qid, "question": q, "model_called": pr.get("model_called"),
            "generated_tokens": pr.get("output_tokens"),
            "generation_ms_plain": (pr.get("timings_ms") or {}).get("generation_ms"),
            "generation_ms_stream": (sr.get("timings_ms") or {}).get("generation_ms"),
            "plain_ttfb_ms": plain["ttfb_ms"], "plain_total_ms": plain["total_ms"],
            "stream_ttfb_ms": stream["ttfb_ms"], "stream_first_text_ms": stream["first_text_ms"],
            "stream_chunks": stream["chunks"], "stream_total_ms": stream["total_ms"],
            "first_text_before_complete": (stream["first_text_ms"] is not None and stream["first_text_ms"] < stream["total_ms"]),
            "final_equals_non_streaming": sr.get("answer") == pr.get("answer") and sr.get("citations") == pr.get("citations"),
            "error": stream["error"],
        }
        rows.append(row)
        print(json.dumps({k: row[k] for k in row if k != "question"}), flush=True)
    gen = [r for r in rows if r["model_called"]]
    summary = {
        "questions": len(rows),
        "first_text_ms": {"median": statistics.median(r["stream_first_text_ms"] for r in gen)} if gen else None,
        "plain_total_ms_median": statistics.median(r["plain_total_ms"] for r in rows),
        "stream_total_ms_median": statistics.median(r["stream_total_ms"] for r in rows),
        "streaming_overhead_ms": [round(r["stream_total_ms"] - r["plain_total_ms"], 1) for r in rows],
        "generation_overhead_ms": [round((r["generation_ms_stream"] or 0) - (r["generation_ms_plain"] or 0), 1) for r in gen],
        "all_final_equal": all(r["final_equals_non_streaming"] for r in rows),
    }
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
