"""Real-model evaluation smoke test on one question. Slow; excluded by default.

Run explicitly:  pytest -m slow
"""

import pytest

from regulus.evaluation import load_dataset, run_evaluation, save_run
from regulus.inference import generate
from regulus.model import load_model, load_tokenizer

pytestmark = pytest.mark.slow


def test_single_question_end_to_end(settings, tmp_path):
    tokenizer = load_tokenizer(settings.model)
    model = load_model(settings.model)
    gen = settings.generation
    gen.do_sample = False
    gen.max_new_tokens = 24
    ds = load_dataset()
    run = run_evaluation(ds.examples[:1], lambda q: generate(model, tokenizer, q, gen), {"pipeline": "smoke"})
    assert run.summary["completed"] == 1
    r = run.results[0]
    assert r.model_answer and r.input_tokens > 0 and r.output_tokens > 0 and r.generation_seconds > 0
    assert save_run(run, tmp_path / "smoke.json").is_file()
