"""ChatSession / thinking-split tests. No model is loaded."""

import pytest

from regulus.inference import ChatSession, split_thinking


def test_history_accumulates_in_order():
    s = ChatSession()
    s.add_user("What is Python?")
    s.add_assistant("A programming language.")
    s.add_user("Give me an example.")
    assert [m["role"] for m in s.messages] == ["user", "assistant", "user"]
    assert s.messages[0]["content"] == "What is Python?"
    assert s.turns == 1


def test_system_prompt_is_first_and_survives_clear():
    s = ChatSession(system_prompt="Be brief.")
    s.add_user("hi")
    s.add_assistant("hello")
    assert s.messages[0] == {"role": "system", "content": "Be brief."}
    s.clear()
    assert s.messages == [{"role": "system", "content": "Be brief."}]
    assert s.turns == 0


def test_clear_without_system_prompt_empties_history():
    s = ChatSession()
    s.add_user("hi")
    s.clear()
    assert s.messages == []


def test_empty_user_message_rejected():
    with pytest.raises(ValueError):
        ChatSession().add_user("   ")


def test_drop_last_user_only_removes_dangling_user_turn():
    s = ChatSession()
    s.add_user("q1")
    s.add_assistant("a1")
    s.drop_last_user()  # last is assistant -> nothing happens
    assert len(s.messages) == 2
    s.add_user("q2")
    s.drop_last_user()
    assert len(s.messages) == 2


def test_transcript_excludes_system():
    s = ChatSession(system_prompt="sys")
    s.add_user("q")
    assert s.transcript() == [{"role": "user", "content": "q"}]


def test_assistant_history_strips_think_block():
    s = ChatSession()
    s.add_user("q")
    s.add_assistant("<think>\nreasoning here\n</think>\n\nFinal answer.")
    assert s.messages[-1]["content"] == "Final answer."


@pytest.mark.parametrize(
    "text,expected",
    [
        ("plain answer", (None, "plain answer")),
        ("<think>\n\n</think>\n\nanswer", (None, "answer")),
        ("<think>why</think>  answer", ("why", "answer")),
        ("  <think>multi\nline</think>\n\nA.\nB.", ("multi\nline", "A.\nB.")),
    ],
)
def test_split_thinking(text, expected):
    assert split_thinking(text) == expected


def test_chat_template_renders_multi_turn(settings):
    """History must render through Qwen's template with every turn present."""
    from regulus.model import ModelLoadError, load_tokenizer

    try:
        tok = load_tokenizer(settings.model, local_files_only=True)
    except ModelLoadError as exc:
        pytest.skip(f"tokenizer not in local cache: {exc}")
    s = ChatSession(system_prompt="Be brief.")
    s.add_user("What is Python?")
    s.add_assistant("A language.")
    s.add_user("Example?")
    text = tok.apply_chat_template(s.messages, tokenize=False, add_generation_prompt=True)
    for snippet in ("Be brief.", "What is Python?", "A language.", "Example?"):
        assert snippet in text
    assert text.rstrip().endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n") or text.rstrip().endswith(
        "<|im_start|>assistant"
    )
