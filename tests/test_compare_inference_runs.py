"""scripts/compare_inference_runs.py: exact, field-by-field equivalence with diffs."""

from __future__ import annotations

import importlib.util

from regulus.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("compare_inference_runs", PROJECT_ROOT / "scripts" / "compare_inference_runs.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)


def row(qid="Q", answer="A requires x [1].", **over):
    r = {"id": qid, "question": "q?", "category": "single", "prompt_sha256": "p", "sources": [{"index": 1}],
         "answer": answer, "citations": [{"label": "21 CFR 1.1"}], "repair": None, "coverage_action": "answer",
         "validation_initial": {"status": "valid", "codes": [], "generated_tokens": 10, "max_new_tokens": 256},
         "validation_final": {"status": "valid", "codes": []}, "citation_support": {}, "generated_tokens": 10,
         "prompt_tokens": 100, "model_called": True}
    r.update(over)
    return r


def test_identical_runs_have_no_differences():
    s, m = cmp.compare({"Q": row()}, {"Q": row()}, "a", "b")
    assert s["identical_in_every_field"] == 1 and m == []


def test_one_character_difference_is_reported_with_its_position_and_a_diff():
    s, m = cmp.compare({"Q": row()}, {"Q": row(answer="A requires y [1].")}, "a", "b")
    assert s["differences_by_field"]["answer"] == 1
    d = m[0]["diffs"]["answer"]
    assert d["divergence"]["char"] == 11 and "-A requires x [1]." in d["diff"] and "+A requires y [1]." in d["diff"]


def test_validation_repair_citation_and_token_differences_are_all_counted():
    b = row(validation_initial={"status": "incomplete", "codes": ["truncated"], "generated_tokens": 12},
            repair="truncation_noted", citations=[], generated_tokens=12)
    s, m = cmp.compare({"Q": row()}, {"Q": b}, "a", "b")
    for f in ("validation_initial", "repair", "citations", "generated_tokens"):
        assert s["differences_by_field"][f] == 1, f
    assert "truncated" in m[0]["diffs"]["validation_initial"]["diff"]


def test_generation_length_fields_inside_validation_are_not_double_counted():
    b = row(validation_initial={"status": "valid", "codes": [], "generated_tokens": 99, "max_new_tokens": 999})
    s, _ = cmp.compare({"Q": row()}, {"Q": b}, "a", "b")
    assert s["differences_by_field"]["validation_initial"] == 0
