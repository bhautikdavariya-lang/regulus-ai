"""Reply cache for evaluation runs (regulus.evaluation.reply_cache, 29 Oct)."""
from regulus.evaluation.reply_cache import CachedGenerator
from regulus.inference.types import GenerationResult

MSG = [{"role": "user", "content": "What does 21 CFR 820.45 require?"}]


class _Fake:
    def __init__(self, revision="r1", do_sample=False, finished=True, stop_reason=None):
        self.calls, self.revision, self.do_sample = 0, revision, do_sample
        self.finished, self.stop_reason = finished, stop_reason

    def describe(self):
        return {"model_id": "m", "model_revision": self.revision, "generation": {"do_sample": self.do_sample}}

    def generate(self, messages, max_new_tokens=None, on_text=None):
        self.calls += 1
        return GenerationResult(prompt="p", response=f"reply {self.calls} ({max_new_tokens})", prompt_tokens=7,
                                generated_tokens=3, seconds=1.5, finished=self.finished, stop_reason=self.stop_reason)


def test_the_same_call_is_replayed_with_every_field(tmp_path):
    real = _Fake(finished=False, stop_reason="repetition")
    gen = CachedGenerator(real, tmp_path / "c.jsonl")
    first = gen.generate(MSG, max_new_tokens=1696)
    again = CachedGenerator(real, tmp_path / "c.jsonl").generate(MSG, max_new_tokens=1696)   # a later run
    assert real.calls == 1
    assert again == first   # finished=False and stop_reason survive: the validator reads both


def test_a_new_token_limit_or_model_revision_is_a_new_call(tmp_path):
    real = _Fake()
    gen = CachedGenerator(real, tmp_path / "c.jsonl")
    gen.generate(MSG, max_new_tokens=1696)
    gen.generate(MSG, max_new_tokens=3072)
    assert real.calls == 2 and gen.counts() == {"fresh": 2, "cached": 0}
    other = _Fake(revision="r2")
    CachedGenerator(other, tmp_path / "c.jsonl").generate(MSG, max_new_tokens=1696)
    assert other.calls == 1


def test_a_sampling_generator_is_never_cached(tmp_path):
    real = _Fake(do_sample=True)
    gen = CachedGenerator(real, tmp_path / "c.jsonl")
    gen.generate(MSG)
    gen.generate(MSG)
    assert real.calls == 2 and not gen.enabled and not (tmp_path / "c.jsonl").exists()


def test_a_damaged_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "c.jsonl"
    real = _Fake()
    CachedGenerator(real, path).generate(MSG, max_new_tokens=10)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"key": "abc", "respon')   # a run killed mid-write
    gen = CachedGenerator(real, path)
    assert gen.skipped_lines == 1
    gen.generate(MSG, max_new_tokens=10)
    assert real.calls == 1 and gen.cached == 1


def test_a_streaming_caller_still_sees_the_replayed_text(tmp_path):
    real = _Fake()
    CachedGenerator(real, tmp_path / "c.jsonl").generate(MSG, max_new_tokens=10)
    seen = []
    out = CachedGenerator(real, tmp_path / "c.jsonl").generate(MSG, max_new_tokens=10, on_text=seen.append)
    assert seen == [out.response]


def test_a_settings_or_adapter_change_after_start_is_a_new_call(tmp_path):
    """The UI sets the decoding settings and the adapter per request: the key reads them at every call."""
    real = _Fake()
    gen = CachedGenerator(real, tmp_path / "c.jsonl")
    gen.generate(MSG, max_new_tokens=10)
    real.revision = "r1+adapter:abc"
    gen.generate(MSG, max_new_tokens=10)
    assert real.calls == 2


def test_wrap_from_env_is_off_unless_a_file_is_named(tmp_path, monkeypatch):
    from regulus.evaluation.reply_cache import wrap_from_env
    real = _Fake()
    monkeypatch.delenv("REGULUS_REPLY_CACHE", raising=False)
    assert wrap_from_env(real) is real
    monkeypatch.setenv("REGULUS_REPLY_CACHE", "off")
    assert wrap_from_env(real) is real
    monkeypatch.setenv("REGULUS_REPLY_CACHE", str(tmp_path / "sub" / "c.jsonl"))
    assert isinstance(wrap_from_env(real), CachedGenerator)


def test_concurrent_callers_write_whole_lines(tmp_path):
    import json
    import threading
    real = _Fake()
    gen = CachedGenerator(real, tmp_path / "c.jsonl")
    threads = [threading.Thread(target=gen.generate, args=([{"role": "user", "content": str(i)}],), kwargs={"max_new_tokens": 5})
               for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = (tmp_path / "c.jsonl").read_text().splitlines()
    assert len(lines) == 20 and all(json.loads(x)["key"] for x in lines)


# ------------------------------------------------------------ replay-only change-impact runs (29 Oct)


def test_replay_only_gives_the_live_answer_without_the_model_and_flags_a_changed_prompt(tmp_path):
    import pytest
    from regulus.evaluation.reply_cache import CacheMiss, ReplayOnlyGenerator
    from regulus.rag import RagConfig, RagPipeline
    from regulus.retrieval import LexicalRetriever
    from tests.test_answer_validation import TWO, ScriptedGenerator
    from tests.test_retrieval_plan import TableDatabase

    path = tmp_path / "c.jsonl"
    good = "21 CFR 820.10(b)(2) requires traceability procedures [1]. 21 CFR 820.10(b)(4) requires advisory notices [2]."
    live = RagPipeline(LexicalRetriever(TableDatabase()), CachedGenerator(ScriptedGenerator(good), path), RagConfig())
    first = live.answer(TWO)
    replay = RagPipeline(LexicalRetriever(TableDatabase()), CachedGenerator(ReplayOnlyGenerator(path), path), RagConfig())
    assert replay.answer(TWO).answer == first.answer
    with pytest.raises(CacheMiss):   # a question never answered live: its prompt is not in the cache
        replay.answer("What does 21 CFR 820.10(b)(2) require?")


def test_cache_miss_is_not_swallowed_by_except_exception():
    from regulus.evaluation.reply_cache import CacheMiss
    assert not issubclass(CacheMiss, Exception)


def test_replay_only_needs_the_recorded_model_identity(tmp_path):
    import pytest
    from regulus.evaluation.reply_cache import ReplayOnlyGenerator
    with pytest.raises(FileNotFoundError):
        ReplayOnlyGenerator(tmp_path / "never_written.jsonl")


def test_impact_select_merge_diff(tmp_path, capsys):
    import json
    import subprocess
    import sys
    from pathlib import Path

    def w(name, rows):
        (tmp_path / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
        return tmp_path / name

    base = w("base.jsonl", [{"id": "A", "answer": "a"}, {"id": "B", "answer": "b"}, {"id": "C", "answer": "c"}])
    replay = w("replay.jsonl", [{"id": "A", "answer": "a"}, {"id": "B", "needs_live": True}, {"id": "C", "answer": "c2"}])
    live = w("live.jsonl", [{"id": "B", "answer": "b2"}])
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"summary": {"selected_ids": ["A", "B", "C"]},
                               "questions": [{"ID": i, "question": i} for i in "ABC"]}))
    script = str(Path(__file__).resolve().parents[1] / "scripts" / "impact_run.py")
    run = lambda *a: subprocess.run([sys.executable, script, *map(str, a)], capture_output=True, text=True, check=True).stdout
    run("select", replay, sel, tmp_path / "need.json")
    assert json.loads((tmp_path / "need.json").read_text())["summary"]["selected_ids"] == ["B"]
    run("merge", replay, live, tmp_path / "merged.jsonl")
    merged = {json.loads(l)["id"]: json.loads(l) for l in (tmp_path / "merged.jsonl").read_text().splitlines()}
    assert merged["B"]["answer"] == "b2" and merged["B"]["impact"] == "live" and merged["A"]["impact"] == "replayed"
    run("diff", base, tmp_path / "merged.jsonl", "--out", tmp_path / "changed.txt")
    assert (tmp_path / "changed.txt").read_text() == "B,C"
