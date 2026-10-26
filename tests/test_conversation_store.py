"""The chat conversation store (regulus.conversations): isolation, ordering, persistence,
idempotent retries and honest failure states. Every test uses its own temporary file."""

from __future__ import annotations

import threading
import uuid

import pytest

from regulus.conversations import (
    ASSISTANT,
    CANCELLED,
    ERROR,
    MAX_QUESTION_CHARS,
    OK,
    USER,
    ConversationNotFound,
    ConversationStore,
    InvalidInput,
    title_from,
)


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "chat.sqlite3")


def turn() -> str:
    return uuid.uuid4().hex


RESULT = {"answer": "Validated answer [1].", "citations": [{"index": 1, "label": "21 CFR 820.10(b)(2)"}],
          "accuracy": {"question_review": {"status": "pass", "label": "PASS"}}}


def ask(store, cid, question, result=RESULT, status=OK):
    t = turn()
    store.add_user_message(cid, t, question)
    store.record_answer(cid, t, status, (result or {}).get("answer", ""), result)
    return t


# ------------------------------------------------------------- persistence and ordering


def test_a_conversation_survives_a_restart(tmp_path):
    path = tmp_path / "chat.sqlite3"
    s1 = ConversationStore(path)
    cid = s1.create_conversation()["id"]
    ask(s1, cid, "What does 21 CFR 820.10(b)(2) require?")
    s2 = ConversationStore(path)                          # a new process opening the same file
    conv = s2.get_conversation(cid)
    assert [m["role"] for m in conv["messages"]] == [USER, ASSISTANT]
    assert conv["messages"][1]["result"] == RESULT        # citations and evaluation kept with the answer


def test_messages_come_back_in_turn_order(store):
    cid = store.create_conversation()["id"]
    for q in ("first question", "second question", "third question"):
        ask(store, cid, q)
    msgs = store.get_conversation(cid)["messages"]
    assert [m["content"] for m in msgs if m["role"] == USER] == ["first question", "second question", "third question"]
    assert [m["role"] for m in msgs] == [USER, ASSISTANT] * 3


def test_an_answer_follows_its_own_question_even_when_turns_overlap(store):
    cid = store.create_conversation()["id"]
    a, b = turn(), turn()
    store.add_user_message(cid, a, "question A")
    store.add_user_message(cid, b, "question B")          # B asked before A was answered
    store.record_answer(cid, b, OK, "answer B", {"answer": "answer B"})
    store.record_answer(cid, a, OK, "answer A", {"answer": "answer A"})
    assert [m["content"] for m in store.get_conversation(cid)["messages"]] == \
        ["question A", "answer A", "question B", "answer B"]


# ------------------------------------------------------------- isolation


def test_conversations_never_share_messages(store):
    c1, c2 = store.create_conversation()["id"], store.create_conversation()["id"]
    ask(store, c1, "about part 11")
    ask(store, c2, "about part 820")
    m1, m2 = store.get_conversation(c1)["messages"], store.get_conversation(c2)["messages"]
    assert {m["conversation_id"] for m in m1} == {c1} and {m["conversation_id"] for m in m2} == {c2}
    assert m1[0]["content"] == "about part 11" and m2[0]["content"] == "about part 820"


def test_the_same_turn_id_in_two_conversations_stays_separate(store):
    c1, c2, t = store.create_conversation()["id"], store.create_conversation()["id"], turn()
    store.add_user_message(c1, t, "q1")
    store.add_user_message(c2, t, "q2")
    store.record_answer(c1, t, OK, "a1", None)
    assert store.answer_for(c2, t) is None
    assert [m["content"] for m in store.get_conversation(c2)["messages"]] == ["q2"]


def test_an_unknown_conversation_is_reported_not_created(store):
    with pytest.raises(ConversationNotFound):
        store.get_conversation(uuid.uuid4().hex)
    with pytest.raises(ConversationNotFound):
        store.add_user_message(uuid.uuid4().hex, turn(), "q")
    assert store.list_conversations() == []


# ------------------------------------------------------------- retries and duplicates


def test_resending_a_turn_stores_one_question(store):
    cid, t = store.create_conversation()["id"], turn()
    _, created = store.add_user_message(cid, t, "q")
    _, again = store.add_user_message(cid, t, "q")
    assert created is True and again is False
    assert len(store.get_conversation(cid)["messages"]) == 1


def test_a_turn_id_cannot_be_reused_for_a_different_question(store):
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")
    with pytest.raises(InvalidInput):
        store.add_user_message(cid, t, "a different question")


def test_a_delivered_answer_is_never_duplicated_or_overwritten(store):
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")
    first = store.record_answer(cid, t, OK, "the answer", {"answer": "the answer"})
    second = store.record_answer(cid, t, OK, "another answer", {"answer": "another answer"})
    third = store.record_answer(cid, t, ERROR, "", None)
    assert second == first and third == first
    assert [m["content"] for m in store.get_conversation(cid)["messages"]] == ["q", "the answer"]


@pytest.mark.parametrize("failed", [ERROR, CANCELLED])
def test_a_failed_attempt_is_replaced_by_a_successful_retry_in_place(store, failed):
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")
    store.record_answer(cid, t, failed, "Request failed: model crashed", None)
    store.record_answer(cid, t, OK, "the answer", {"answer": "the answer"})
    msgs = store.get_conversation(cid)["messages"]
    assert [(m["role"], m["status"], m["content"]) for m in msgs] == [(USER, OK, "q"), (ASSISTANT, OK, "the answer")]


# ------------------------------------------------------------- honest failure states


@pytest.mark.parametrize("status", [ERROR, CANCELLED])
def test_a_failed_turn_is_recorded_as_failed_not_as_an_answer(store, status):
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")
    store.record_answer(cid, t, status, "generation failed", None)
    reply = store.get_conversation(cid)["messages"][1]
    assert reply["status"] == status and reply["result"] is None


def test_an_interrupted_turn_keeps_its_question_and_has_no_reply(store):
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")                   # the process died before the answer was recorded
    assert store.answer_for(cid, t) is None
    assert [m["role"] for m in store.get_conversation(cid)["messages"]] == [USER]


def test_an_answer_needs_its_question(store):
    cid = store.create_conversation()["id"]
    with pytest.raises(InvalidInput):
        store.record_answer(cid, turn(), OK, "orphan answer", None)


# ------------------------------------------------------------- input limits, titles, listing


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_QUESTION_CHARS + 1), None, 42])
def test_bad_questions_are_refused(store, bad):
    cid = store.create_conversation()["id"]
    with pytest.raises(InvalidInput):
        store.add_user_message(cid, turn(), bad)


@pytest.mark.parametrize("bad", ["", "short", "has space in it", "x" * 65, "../etc/passwd", None])
def test_bad_ids_are_refused(store, bad):
    with pytest.raises(InvalidInput):
        store.get_conversation(bad)


def test_the_title_is_the_first_question_and_is_kept(store):
    cid = store.create_conversation()["id"]
    ask(store, cid, "  What   does 21 CFR Part 11 cover?  ")
    ask(store, cid, "And what about electronic signatures?")
    assert store.get_conversation(cid)["title"] == "What does 21 CFR Part 11 cover?"


def test_a_long_title_is_cut_at_a_word():
    title = title_from("word " * 40)
    assert len(title) <= 80 and title.endswith("…") and "  " not in title


def test_the_list_is_most_recently_active_first(store):
    c1, c2 = store.create_conversation()["id"], store.create_conversation()["id"]
    ask(store, c1, "older")
    ask(store, c2, "newer")
    ask(store, c1, "c1 again")                            # c1 is now the most recently active
    listed = store.list_conversations()
    assert [c["id"] for c in listed] == [c1, c2]
    assert listed[0]["message_count"] == 4


def test_an_oversized_result_is_stored_without_its_evidence_snapshot(store, monkeypatch):
    import regulus.conversations.store as S

    monkeypatch.setattr(S, "MAX_RESULT_BYTES", 2000)
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")
    big = {**RESULT, "evidence_snapshot": {"items": ["x" * 5000]}}
    stored = store.record_answer(cid, t, OK, RESULT["answer"], big)["result"]
    assert "evidence_snapshot" not in stored and stored["_stored_without"] == ["evidence_snapshot"]
    assert stored["citations"] == RESULT["citations"]


# ------------------------------------------------------------- concurrent writers


def test_concurrent_writers_lose_nothing(store):
    cid = store.create_conversation()["id"]
    errors = []

    def worker(n):
        try:
            ask(store, cid, f"question {n}")
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    msgs = store.get_conversation(cid)["messages"]
    assert len(msgs) == 24 and [m["role"] for m in msgs] == [USER, ASSISTANT] * 12


# ------------------------------------------------------------- deleting a conversation


def _raw_count(store, cid):
    import sqlite3

    db = sqlite3.connect(store.path)
    try:
        return db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (cid,)).fetchone()[0]
    finally:
        db.close()


def test_delete_removes_the_conversation_and_all_its_messages(store):
    cid = store.create_conversation()["id"]
    ask(store, cid, "first question")
    ask(store, cid, "second question")
    assert store.delete_conversation(cid) == {"id": cid, "messages_deleted": 4}
    with pytest.raises(ConversationNotFound):
        store.get_conversation(cid)
    assert cid not in [c["id"] for c in store.list_conversations()]
    assert _raw_count(store, cid) == 0                     # no orphaned message is left behind


def test_delete_leaves_other_conversations_alone(store):
    c1, c2 = store.create_conversation()["id"], store.create_conversation()["id"]
    ask(store, c1, "about part 11")
    ask(store, c2, "about part 820")
    before = store.get_conversation(c2)
    store.delete_conversation(c1)
    assert store.get_conversation(c2) == before
    assert [c["id"] for c in store.list_conversations()] == [c2]


def test_deleting_a_missing_conversation_is_reported(store):
    with pytest.raises(ConversationNotFound):
        store.delete_conversation(uuid.uuid4().hex)
    cid = store.create_conversation()["id"]
    store.delete_conversation(cid)
    with pytest.raises(ConversationNotFound):              # a second delete finds nothing
        store.delete_conversation(cid)


@pytest.mark.parametrize("bad", ["", "short", "has space in it", "x" * 65, "../etc/passwd", None])
def test_delete_refuses_bad_ids(store, bad):
    with pytest.raises(InvalidInput):
        store.delete_conversation(bad)


def test_an_answer_for_a_deleted_conversation_is_refused_not_resurrected(store):
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "q")                   # a turn still being answered
    store.delete_conversation(cid)
    with pytest.raises(InvalidInput):
        store.record_answer(cid, t, OK, "late answer", {"answer": "late answer"})
    assert store.list_conversations() == []
    assert _raw_count(store, cid) == 0


def test_deleted_text_does_not_linger_in_the_database_files(store):
    """secure_delete zeroes the freed cells and the WAL is truncated, so the question and answer of a deleted
    conversation cannot be read back from the file (without it, both stay in the free pages)."""
    keep = store.create_conversation()["id"]
    t0 = turn()
    store.add_user_message(keep, t0, "kept question")
    store.record_answer(keep, t0, OK, "kept answer", {"answer": "kept answer"})
    cid, t = store.create_conversation()["id"], turn()
    store.add_user_message(cid, t, "SECRET-QUESTION-zq81 about Part 11")
    store.record_answer(cid, t, OK, "SECRET-ANSWER-zq81", {"answer": "SECRET-ANSWER-zq81", "accuracy": {"note": "zq81"}})
    store.delete_conversation(cid)
    files = [p for p in store.path.parent.iterdir() if p.is_file() and p.name.startswith(store.path.name)]
    blob = b"".join(p.read_bytes() for p in files)
    assert b"zq81" not in blob and b"SECRET-QUESTION" not in blob
    assert b"kept answer" in blob                          # what was kept is still there
    assert store.get_conversation(keep)["messages"][1]["content"] == "kept answer"
