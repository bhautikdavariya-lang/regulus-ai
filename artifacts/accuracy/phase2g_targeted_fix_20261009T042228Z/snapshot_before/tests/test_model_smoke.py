"""Full model load + generation. Slow; excluded by default.

Run explicitly:  pytest -m slow
"""

import pytest

from regulus.inference import generate
from regulus.model import load_model, load_tokenizer

pytestmark = pytest.mark.slow


def test_model_generates_text(settings):
    tokenizer = load_tokenizer(settings.model)
    model = load_model(settings.model)
    gen = settings.generation
    gen.max_new_tokens = 16
    gen.do_sample = False
    result = generate(model, tokenizer, "Say hello.", gen)
    assert result.generated_tokens > 0
    assert result.response.strip()
