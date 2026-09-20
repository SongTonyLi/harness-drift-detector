import pytest

from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    SystemEvent,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
    event_to_record,
    header_to_record,
    record_to_event,
    record_to_header,
)


def test_assistant_roundtrip():
    ev = AssistantEvent(
        seq=15,
        turn=1,
        step=1,
        text="hi",
        tool_calls=(ToolCall("c1", "bash", '{"command":"ls"}'),),
        stop_reason="toolUse",
    )
    rec = event_to_record(ev)
    assert list(rec)[0] == "kind" and rec["kind"] == "assistant"
    assert rec["tool_calls"] == [
        {"call_id": "c1", "name": "bash", "arguments": '{"command":"ls"}'}
    ]
    assert record_to_event(rec) == ev


def test_all_kinds_roundtrip():
    events = [
        SystemEvent(7, 1, 1, "sys"),
        UserEvent(8, 1, "hello", "human"),
        ToolResultEvent(17, 1, 1, "c1", "bash", "out", False),
        TurnEndEvent(30, 1, "completed"),
    ]
    for ev in events:
        rec = event_to_record(ev)
        assert list(rec)[0] == "kind"
        assert record_to_event(rec) == ev


def test_header_roundtrip_and_unknown_kind():
    h = TranscriptHeader("s1", "dsh", "/p", model="m", provider="p", cwd="/c", created_at=1)
    rec = header_to_record(h)
    assert list(rec)[0] == "kind" and rec["kind"] == "transcript"
    assert record_to_header(rec) == h
    with pytest.raises(ValueError):
        record_to_event({"kind": "nope"})
    with pytest.raises(ValueError):
        record_to_header({"kind": "user"})


def test_records_are_json_scalars_only():
    rec = event_to_record(
        AssistantEvent(1, 1, 1, "t", (ToolCall("c", "bash", "{}"),), None)
    )
    assert rec["stop_reason"] is None
    assert all(isinstance(v, (str, int, bool, list, type(None))) for v in rec.values())


def test_optional_keys_default():
    ev = record_to_event({"kind": "assistant", "seq": 1, "turn": 1, "step": 1, "text": "x"})
    assert ev == AssistantEvent(1, 1, 1, "x", (), None)
    res = record_to_event(
        {"kind": "tool_result", "seq": 2, "turn": 1, "step": 1, "call_id": "c", "name": "bash", "text": "o"}
    )
    assert res.is_error is False
    header = record_to_header({"kind": "transcript", "transcript_id": "s", "harness": "dsh", "source_path": "/p"})
    assert header == TranscriptHeader("s", "dsh", "/p")


def test_transcript_helpers():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "a", "human"),
            AssistantEvent(2, 1, 1, "x"),
            TurnEndEvent(3, 1, "completed"),
            UserEvent(4, 2, "b", "human"),
            AssistantEvent(5, 2, 1, "y"),
        ),
    )
    assert t.transcript_id == "s1"
    assert t.turn_numbers() == [1, 2]
    assert [e.seq for e in t.assistant_steps()] == [2, 5]


def test_transcript_helpers_are_sorted_and_deduped():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            AssistantEvent(5, 2, 1, "y"),
            AssistantEvent(2, 1, 1, "x"),
            TurnEndEvent(3, 1, "completed"),
        ),
    )
    assert t.turn_numbers() == [1, 2]
    assert [e.seq for e in t.assistant_steps()] == [2, 5]
