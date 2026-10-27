"""Dynamic answer examples (FX1, 27 Oct 2026): one verified example of what a complete answer covers, chosen for the
question by embedding similarity, shown in the prompt as an example of form only.

Retrieval systems show a model a solved example like the task at hand (dynamic few-shot). The examples are the client
bank's verified keys of the DEV split (a local file outside the repository, REGULUS_ANSWER_EXAMPLES); sealed questions are never in it. An
example never comes from a provision the question's own evidence covers, nor from a question that is (nearly) the
question asked - so the benchmark's own key never answers its question; and its section numbers are replaced, so no
citation can be copied from it. What it shows is coverage: each paragraph's rule, its conditions, its exceptions.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import numpy as np

# the examples are the client's verified keys: kept outside the repository, at REGULUS_ANSWER_EXAMPLES (no file: no example)
PATH = Path(os.environ.get("REGULUS_ANSWER_EXAMPLES", "") or Path.home() / "regulus_eval_runs" / "answer_examples_v1.json")
NEAR_DUPLICATE = 0.85   # an example question this similar to the question asked is the same question
_LOCK = threading.Lock()
_CACHE: dict[int, tuple] = {}


def _load(embedder) -> tuple[list[dict], np.ndarray]:
    with _LOCK:
        key = id(embedder)
        if key not in _CACHE:
            examples = json.loads(PATH.read_text(encoding="utf-8"))["examples"]
            vecs = np.array([embedder.embed_query(e["question"]) for e in examples], dtype=np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
            _CACHE[key] = (examples, vecs)
        return _CACHE[key]


def choose(embedder, question: str, covered_sections: set[str]) -> dict | None:
    """The example most similar to `question` that is about none of `covered_sections` ("70.3", "FDCA607") and is
    not the question itself; None without the embedder or a candidate."""
    if embedder is None or not question:
        return None
    examples, vecs = _load(embedder)
    q = np.asarray(embedder.embed_query(question), dtype=np.float32)
    q /= np.linalg.norm(q)
    sims = vecs @ q
    norm = " ".join(question.lower().split())
    for i in np.argsort(-sims):
        e = examples[int(i)]
        if sims[i] >= NEAR_DUPLICATE or " ".join(e["question"].lower().split()) == norm:
            continue
        if set(e["sections"]) & covered_sections:
            continue
        return e
    return None


def covered(package) -> set[str]:
    """The sections (and FD&C Act sections as "FDCA607") the package's evidence and requests are about."""
    out: set[str] = set()
    for s in package.sources:
        m = re.match(r"^21 CFR (\d+\.\d+[a-z]?)", s.citation or "")
        if m:
            out.add(m.group(1))
        m = re.match(r"^FD&C Act § (\d{3})", s.citation or "")
        if m:
            out.add("FDCA" + m.group(1))
    for _, label in package.requirements:
        m = re.match(r"^21 CFR (\d+\.\d+[a-z]?)", label)
        if m:
            out.add(m.group(1))
    return out
