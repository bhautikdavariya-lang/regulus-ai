"""Deterministic identities for what an evaluation measured, besides the weights.

An evaluation result means something only relative to three things: the
weights (`ModelIdentity`), the questions (`BenchmarkIdentity` plus the
question set below), and the pipeline that turned a question into an answer.
This module owns the last two. It is pure data in, data out: stdlib only, no
clock, no randomness, no machine state, so the evaluator that writes an
identity and the dashboard that checks it compute the same value.

Pipeline fingerprint
--------------------
`normalize_evaluation_config` keeps exactly the fields listed in
`FINGERPRINT_FIELDS`, in these sections, and drops everything else:

    retrieval         retriever, top_k, corpus, min_trigram_similarity,
                      exclude_contextual_only
    coverage          no_context_behavior, incomplete_behavior, answerability, optional_context,
                      scope_policy, evidence_consolidation
    context           max_results, max_chars_per_result, max_total_chars,
                      hard_max_results, hard_max_total_chars,
                      required_max_chars_per_result, binding_reserve_chars
    generation_budget policy, base_tokens, per_unit_tokens, range_bonus_tokens,
                      general_tokens, max_units, min_tokens, evidence_multiple,
                      evidence_cap_fraction, hard_max_tokens
    decoding          do_sample, temperature, top_p, top_k, enable_thinking,
                      repetition_penalty, no_repeat_ngram_size
    validation        validation_behavior
    repair            mode
    prompt            system_prompt_sha256, answer_shape

A listed field that is absent becomes an explicit null, so "not recorded"
and "recorded as X" never hash alike by accident. Under greedy decoding
(`do_sample` false) temperature, top_p and top_k do not influence the output,
so they are normalised to null: changing them then changes nothing, which is
the truth. Integral floats are written as integers (1.0 and 1 are the same
setting).

Deliberately excluded, because they do not change what an answer is:
timestamps, run ids, file paths, the model cache directory, device and dtype
(those belong to the model identity), `generation.max_new_tokens` from
`configs/model.yaml` (the pipeline always passes its own per-question budget,
so the global value is never used), and whether the controlled condition ran
(it adds a second measurement; it does not change the full-pipeline one).

The digest is sha256 over the canonical JSON of
`{"fingerprint_version": FINGERPRINT_VERSION, "config": <normalised>}`.
Canonical JSON is `json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` encoded as UTF-8. Adding, removing or reinterpreting a
field requires bumping `FINGERPRINT_VERSION`, so two fingerprints of
different versions are never compared as if they were the same scheme.

Known gap: the pipeline's code is not fingerprinted. The system prompt text
is (by hash), but a change to retrieval or validation code with no
configuration change produces the same fingerprint. The project has no
version control to record a revision from.

Question set
------------
`question_set_identity` is sha256 over the canonical JSON of the sorted,
de-duplicated list of question ids, e.g. `["S5-001","S5-002"]`. It depends
only on which questions were evaluated, never on their order, so a
51-question run and a 2-question smoke run on the same benchmark file have
different identities, and a run covers the benchmark only when its identity
equals the identity of the benchmark's full id list.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

ALGORITHM = "sha256"
# 2: the prompt section gained answer_shape (Stage 12 answer shaping changes the
#    user turn and the evidence selection); version-1 fingerprints predate it.
# 3: the coverage section gained answerability (the Stage 5 gate decides whether
#    the model is called at all; docs/answerability_gate_stage5.md).
# 4: the coverage section gained optional_context (Stage 6 exact-evidence context;
#    docs/generation_quality_stage6.md).
# 5: retrieval gained semantic_fallback, coverage gained scope_policy (Stage 7;
#    docs/retrieval_validation_stage7.md).
# 6: coverage gained evidence_consolidation (Stage 8; docs/generation_control_stage8.md).
# 7: context gained binding_reserve_chars (RC2: part of the optional budget offered to eCFR first
#    for a question that names no provision; regulus.rag.context.ContextPolicy).
FINGERPRINT_VERSION = 7
QUESTION_SET_VERSION = 1

FINGERPRINT_FIELDS: dict[str, tuple[str, ...]] = {
    "retrieval": ("retriever", "top_k", "corpus", "min_trigram_similarity", "exclude_contextual_only", "semantic_fallback"),
    "coverage": ("no_context_behavior", "incomplete_behavior", "answerability", "optional_context", "scope_policy", "evidence_consolidation"),
    "context": (
        "max_results", "max_chars_per_result", "max_total_chars",
        "hard_max_results", "hard_max_total_chars", "required_max_chars_per_result", "binding_reserve_chars",
    ),
    "generation_budget": (
        "policy", "base_tokens", "per_unit_tokens", "range_bonus_tokens", "general_tokens",
        "max_units", "min_tokens", "evidence_multiple", "evidence_cap_fraction", "hard_max_tokens",
    ),
    "decoding": (
        "do_sample", "temperature", "top_p", "top_k", "enable_thinking",
        "repetition_penalty", "no_repeat_ngram_size",
    ),
    "validation": ("validation_behavior",),
    "repair": ("mode",),
    "prompt": ("system_prompt_sha256", "answer_shape"),
}

# Sampling parameters that greedy decoding ignores.
_SAMPLING_ONLY = ("temperature", "top_p", "top_k")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normal_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, Mapping):
        return {str(k): _normal_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal_value(v) for v in value]
    return str(value)


def normalize_evaluation_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """The evaluation-relevant configuration, and nothing else, in canonical form."""
    out: dict[str, Any] = {}
    for section, fields in FINGERPRINT_FIELDS.items():
        source = config.get(section)
        if source is None:
            out[section] = None  # the section was not recorded at all
            continue
        if not isinstance(source, Mapping):
            raise ValueError(f"evaluation_config section {section!r} must be an object")
        out[section] = {name: _normal_value(source.get(name)) for name in fields}
    decoding = out.get("decoding")
    if decoding is not None and decoding.get("do_sample") is False:
        for name in _SAMPLING_ONLY:
            decoding[name] = None
    return out


@dataclass(frozen=True)
class PipelineFingerprint:
    version: int
    algorithm: str
    value: str

    @property
    def short(self) -> str:
        return self.value[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "PipelineFingerprint | None":
        """Read a recorded fingerprint, or None if it is absent or malformed."""
        if not isinstance(data, Mapping):
            return None
        version, algorithm, value = data.get("version"), data.get("algorithm"), data.get("value")
        if not isinstance(version, int) or algorithm != ALGORITHM or not isinstance(value, str) or len(value) != 64:
            return None
        return cls(version=version, algorithm=algorithm, value=value)


def pipeline_fingerprint(config: Mapping[str, Any]) -> PipelineFingerprint:
    normalized = normalize_evaluation_config(config)
    payload = canonical_json({"fingerprint_version": FINGERPRINT_VERSION, "config": normalized})
    return PipelineFingerprint(version=FINGERPRINT_VERSION, algorithm=ALGORITHM, value=_sha256(payload))


def config_differences(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every fingerprinted field on which two configurations differ.

    Two hashes tell a reader that a run measured a different pipeline; they do
    not tell anyone WHICH setting differs, which is the only form in which the
    information is actionable. A field absent from one side appears here with
    `null`, because `normalize_evaluation_config` has already turned "not
    recorded" into an explicit null -- so this also distinguishes "configured
    differently" from "never recorded".

    Pure comparison over the normalised forms: it adds nothing to the digest
    and cannot change any fingerprint.
    """
    left, right = normalize_evaluation_config(a), normalize_evaluation_config(b)
    out: list[dict[str, Any]] = []
    for section in FINGERPRINT_FIELDS:
        ls, rs = left.get(section), right.get(section)
        if ls == rs:
            continue
        if ls is None or rs is None:
            out.append({"field": section, "recorded": ls, "current": rs,
                        "note": "the whole section is absent on one side"})
            continue
        for name in FINGERPRINT_FIELDS[section]:
            if ls.get(name) != rs.get(name):
                out.append({"field": f"{section}.{name}", "recorded": ls.get(name), "current": rs.get(name),
                            "note": ("not recorded by the run" if ls.get(name) is None else
                                     "not recorded by the current configuration" if rs.get(name) is None else
                                     "configured differently")})
    return out


@dataclass(frozen=True)
class QuestionSetIdentity:
    sha256: str
    count: int
    version: int = QUESTION_SET_VERSION
    algorithm: str = ALGORITHM

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def question_set_identity(ids: Iterable[str]) -> QuestionSetIdentity:
    unique = sorted({str(i) for i in ids})
    return QuestionSetIdentity(sha256=_sha256(canonical_json(unique)), count=len(unique))
