"""Tests for the LibreChat adapter (mongodb → memloom pairing)."""
from __future__ import annotations

from memloom.collectors.librechat import (
    _pair_into_turns,
    _format_turn,
    _shorten_title,
)


# ---------- pairing ----------


def test_pair_basic_qa():
    msgs = [
        {"sender": "User", "text": "hi", "messageId": "m1", "createdAt": "2026-01-01"},
        {"sender": "Assistant", "text": "hello", "messageId": "m2", "createdAt": "2026-01-02"},
    ]
    turns = list(_pair_into_turns(msgs))
    assert len(turns) == 1
    assert [m["sender"] for m in turns[0]] == ["User", "Assistant"]


def test_pair_multi_turn():
    msgs = [
        {"sender": "User", "text": "q1", "messageId": "m1", "createdAt": "2026-01-01"},
        {"sender": "Assistant", "text": "a1", "messageId": "m2", "createdAt": "2026-01-02"},
        {"sender": "User", "text": "q2", "messageId": "m3", "createdAt": "2026-01-03"},
        {"sender": "Assistant", "text": "a2", "messageId": "m4", "createdAt": "2026-01-04"},
    ]
    turns = list(_pair_into_turns(msgs))
    assert len(turns) == 2


def test_pair_continuation_collapses_consecutive_assistants():
    """Tool calls or continuations: multiple Assistant msgs before next User
    should collapse into the previous turn."""
    msgs = [
        {"sender": "User", "text": "q1", "messageId": "m1", "createdAt": "2026-01-01"},
        {"sender": "Assistant", "text": "a1", "messageId": "m2", "createdAt": "2026-01-02"},
        {"sender": "Assistant", "text": "a1 cont", "messageId": "m3", "createdAt": "2026-01-03"},
        {"sender": "User", "text": "q2", "messageId": "m4", "createdAt": "2026-01-04"},
        {"sender": "Assistant", "text": "a2", "messageId": "m5", "createdAt": "2026-01-05"},
    ]
    turns = list(_pair_into_turns(msgs))
    assert len(turns) == 2
    assert [m["sender"] for m in turns[0]] == ["User", "Assistant", "Assistant"]
    assert [m["sender"] for m in turns[1]] == ["User", "Assistant"]


def test_pair_empty_messages_filtered():
    """Empty / whitespace-only messages should be skipped."""
    msgs = [
        {"sender": "User", "text": "", "messageId": "m1", "createdAt": "2026-01-01"},
        {"sender": "Assistant", "text": "hi", "messageId": "m2", "createdAt": "2026-01-02"},
    ]
    turns = list(_pair_into_turns(msgs))
    # Empty User is dropped; Assistant becomes standalone
    assert len(turns) == 1
    assert [m["sender"] for m in turns[0]] == ["Assistant"]


def test_pair_empty_input_returns_no_turns():
    assert list(_pair_into_turns([])) == []


def test_pair_only_whitespace_skipped():
    msgs = [
        {"sender": "User", "text": "   \n  ", "messageId": "m1", "createdAt": "2026-01-01"},
        {"sender": "Assistant", "text": "real content", "messageId": "m2", "createdAt": "2026-01-02"},
    ]
    turns = list(_pair_into_turns(msgs))
    assert len(turns) == 1
    assert [m["sender"] for m in turns[0]] == ["Assistant"]


# ---------- format ----------


def test_format_turn_marks_user_and_assistant():
    turn = [
        {"sender": "User", "text": "question?", "createdAt": "2026-01-01"},
        {"sender": "Assistant", "text": "answer.", "model": "openai/gpt-4o", "createdAt": "2026-01-02"},
    ]
    out = _format_turn(turn)
    assert "**USER**" in out
    assert "**ASSISTANT**" in out
    assert "question?" in out
    assert "answer." in out
    assert "gpt-4o" in out  # model suffix


def test_shorten_title():
    assert _shorten_title("My Chat Title") == "My_Chat_Title"
    assert _shorten_title("") is None
    assert _shorten_title(None) is None
    # spaces become underscores, slashes become dashes
    assert "/" in _shorten_title("a/b") or _shorten_title("a/b") == "a-b"
    # truncates to 50
    long = "a" * 100
    assert len(_shorten_title(long)) == 50
