"""Real-model trial of the value plan BEFORE it touches src/: the planned lines are injected into
the user message on its way to the model, through the production engine (greedy, configured
adapter). Retrieval, validation, repair and citation mapping run unchanged."""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(Path(__file__).parent))
from prompts import PROBES  # noqa: E402

PLAN = json.loads((Path(__file__).parent / "prototype.json").read_text())
FOCUS_ONLY = ("ANSWER FORMAT: plain sentences stating only what the requested provision says about the focus, each "
              "ending with the source number in brackets. Do not describe the rest of the provision. ")
FORMATS = {
    "B": ("ANSWER FORMAT: the question asks for a time period, and the requested provision states more than one. In "
          "plain sentences, give each period listed under \"periods stated\" in the words given there, with the reports "
          "it applies to and when it runs from, each sentence ending with that period's own source number in brackets. "
          "Do not give a period for any other reports, and do not describe the rest of the provision. "),
    "A": ("ANSWER FORMAT: the question asks for a time period, and the requested provision states more than one. Give "
          "each period named under \"periods stated\" with the reports it is named with there, in plain sentences, each "
          "ending with that period's source number in brackets. Do not give a period for any other reports, and do not "
          "describe the rest of the provision. "),
}


_SENT_END = re.compile(r"(?<=[a-z0-9)])\.(?=\s|$)")
_CLAUSE_BREAK = re.compile(r"[,;:]\s+|(?<=[.])\s+")
_LEAD_CONJ = re.compile(r"^(?:but|and|or|then|so)\s+", re.I)


def value_clause(text, value):
    """The source's own words around the stated period: from the clause boundary before it to the end
    of its sentence, verbatim. Keeps the event the period runs from and any cross-reference after it."""
    num = value.split()[0]
    m = re.search(rf"\b{re.escape(num)}[\s-]+(?:(?:calendar|working|business)[\s-]+)?(?:days?|weeks?|months?|years?|hours?)\b",
                  text, re.I)
    if not m:
        return None
    end = _SENT_END.search(text, m.end())
    stop = end.start() if end else len(text)
    starts = [b.end() for b in _CLAUSE_BREAK.finditer(text, 0, m.start())]
    clause = text[starts[-1] if starts else 0:stop].strip()
    return _LEAD_CONJ.sub("", clause)


def source_text(prompt, i):
    m = re.search(rf"SOURCE {i}\n.*?Text:\n(.*?)(?=\n\nSOURCE \d+\n|\n>>>END)", prompt, re.S)
    return m.group(1) if m else ""


def plan_line_b(entries, prompt):
    parts = []
    for v, i, h in entries:
        c = value_clause(source_text(prompt, i), v)
        parts.append(f"{h}: {c} [{i}]" if c else f"{h}: {v} [{i}]")
    return "  periods stated, each with the reports it applies to and when it runs from: " + "; ".join(parts)


def plan_line(entries):
    return ("  periods stated, each with the reports it applies to: "
            + "; ".join(f"{v} for {h} [{i}]" for v, i, h in entries))


def main():
    out_path, variant = Path(sys.argv[1]), sys.argv[2]
    want = set(sys.argv[3:])
    from regulus.config import load_settings
    from regulus.rag import generator as G
    from serve_ui import Engine
    state = {"entries": None, "changed": False, "prompt": None}
    real = G.QwenGenerator.generate

    def patched(self, messages, max_new_tokens=None, on_text=None):
        msgs = [dict(m) for m in messages]
        t = msgs[-1]["content"]
        if state["entries"] and variant != "baseline":
            line = plan_line_b(state["entries"], t) if variant == "B" else plan_line(state["entries"])
            t2 = re.sub(r"(\n  focus: [^\n]*)", lambda m: m.group(1) + "\n" + line, t, count=1)
            t2 = t2.replace(FOCUS_ONLY, FORMATS[variant])
            state["changed"] = t2 != t
            t = t2
        msgs[-1]["content"] = t
        state["prompt"] = t
        return real(self, msgs, max_new_tokens=max_new_tokens, on_text=on_text)

    G.QwenGenerator.generate = patched
    engine = Engine(load_settings(), offline=True)
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    for qid, q in PROBES:
        if want and qid not in want:
            continue
        p = PLAN.get(qid, {})
        state.update(entries=p.get("entries") if p.get("fires") else None, changed=False, prompt=None)
        r = engine.ask(q, accuracy=False)
        a = r.get("answer") or ""
        rec = {"answer": a, "sha": hashlib.sha256(a.encode()).hexdigest()[:16], "changed": state["changed"],
               "fires": bool(p.get("fires")), "out": r.get("output_tokens"), "seven": "7 calendar" in a,
               "fifteen": "15 calendar" in a, "cited": [c["label"] for c in r.get("citations") or [] if c.get("cited_in_answer")],
               "prompt": state["prompt"]}
        out.setdefault(qid, {})[variant] = rec
        print(f"{qid:<14} {variant:<8} fires={str(rec['fires']):<5} changed={str(rec['changed']):<5} 7d={str(rec['seven']):<5} "
              f"15d={str(rec['fifteen']):<5} out={rec['out']:<4} sha={rec['sha']}", flush=True)
        out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
