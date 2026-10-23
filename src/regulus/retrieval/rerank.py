"""Cross-encoder reranking: a small model reads the question together with a provision's text and scores whether the
provision answers it.

Why (23 Oct 2026): the section picker judged candidates by a heading and a 200-character snippet, so it matched words,
not meaning ("filing ... statement" -> 720.9 instead of 720.2 "Times for filing"; "records" -> 80.39 for an FD&C Act 610
question). A cross-encoder reads each candidate paragraph whole, so the paragraph that answers the question decides,
wherever it sits in its section.

Models are pinned by revision and loaded from the repository's local model cache only (models/, never downloaded at
run time). Two kinds:
  * "seqcls": a sequence-classification cross-encoder (BAAI bge-reranker); the score is the logit through a sigmoid.
  * "qwen3": Qwen3-Reranker, a causal LM asked to answer yes or no under an instruction; the score is P(yes).
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

MODEL_CACHE = Path(__file__).resolve().parents[3] / "models"
RERANKERS = {
    "bge-m3": {"repo": "BAAI/bge-reranker-v2-m3", "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "kind": "seqcls"},
    "bge-base": {"repo": "BAAI/bge-reranker-base", "revision": "2cfc18c9415c912f9d8155881c133215df768a70", "kind": "seqcls"},
    "qwen3-0.6b": {"repo": "Qwen/Qwen3-Reranker-0.6B", "revision": "e61197ed45024b0ed8a2d74b80b4d909f1255473", "kind": "qwen3"},
}
INSTRUCTION = ("Given a question a cosmetics or color-additive company asks about U.S. FDA rules, judge whether this "
               "provision of 21 CFR or of the FD&C Act states the rule that answers the question")
MAX_LENGTH = 512
_QWEN_PREFIX = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct "
                "provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
_QWEN_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class Reranker:
    def __init__(self, name: str, device: str | None = None, cache_dir: Path = MODEL_CACHE) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoModelForSequenceClassification, AutoTokenizer

        spec = RERANKERS[name]
        self.name, self.kind, self.revision = name, spec["kind"], spec["revision"]
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        dtype = torch.float16 if self.device == "mps" else torch.float32
        kw = {"revision": spec["revision"], "cache_dir": str(cache_dir), "local_files_only": True}
        if self.kind == "qwen3":
            self.tok = AutoTokenizer.from_pretrained(spec["repo"], padding_side="left", **kw)
            self.model = AutoModelForCausalLM.from_pretrained(spec["repo"], dtype=dtype, **kw).to(self.device).eval()
            self.yes = self.tok.convert_tokens_to_ids("yes")
            self.no = self.tok.convert_tokens_to_ids("no")
            self.prefix = self.tok.encode(_QWEN_PREFIX, add_special_tokens=False)
            self.suffix = self.tok.encode(_QWEN_SUFFIX, add_special_tokens=False)
        else:
            self.tok = AutoTokenizer.from_pretrained(spec["repo"], **kw)
            self.model = AutoModelForSequenceClassification.from_pretrained(spec["repo"], dtype=dtype, **kw).to(self.device).eval()
        self._lock = threading.Lock()

    def describe(self) -> dict:
        return {"reranker": self.name, "repo": RERANKERS[self.name]["repo"], "revision": self.revision, "device": self.device}

    def score(self, query: str, passages: list[str], batch: int = 16) -> np.ndarray:
        """One score per passage, higher = more likely to answer the query (0..1)."""
        import torch

        out: list[float] = []
        with self._lock, torch.inference_mode():
            for i in range(0, len(passages), batch):
                chunk = passages[i:i + batch]
                if self.kind == "qwen3":
                    texts = [f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {p}" for p in chunk]
                    enc = self.tok(texts, padding=False, truncation="longest_first", return_attention_mask=False,
                                   max_length=MAX_LENGTH - len(self.prefix) - len(self.suffix))
                    enc["input_ids"] = [self.prefix + ids + self.suffix for ids in enc["input_ids"]]
                    enc = self.tok.pad(enc, padding=True, return_tensors="pt").to(self.device)
                    logits = self.model(**enc).logits[:, -1, :]
                    pair = torch.stack([logits[:, self.no], logits[:, self.yes]], dim=1).float()
                    out += torch.softmax(pair, dim=1)[:, 1].cpu().tolist()
                else:
                    enc = self.tok([[query, p] for p in chunk], padding=True, truncation=True, max_length=MAX_LENGTH,
                                   return_tensors="pt").to(self.device)
                    out += torch.sigmoid(self.model(**enc).logits.view(-1).float()).cpu().tolist()
            if self.device == "mps":
                # the MPS allocator keeps freed blocks cached; on an 8 GB Mac they crowd the answering model's memory
                torch.mps.empty_cache()
        return np.asarray(out, dtype=np.float32)


_LOCK = threading.Lock()
_CACHE: dict[str, Reranker | None] = {}


def reranker(name: str) -> Reranker | None:
    """The named reranker, loaded once per process; None when its files are not in the local model cache."""
    with _LOCK:
        if name not in _CACHE:
            try:
                _CACHE[name] = Reranker(name)
            except Exception:  # noqa: BLE001 - an aid: callers fall back to the ranking they had
                _CACHE[name] = None
        return _CACHE[name]
