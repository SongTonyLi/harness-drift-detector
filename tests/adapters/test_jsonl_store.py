import json

import pytest

from harness_drift_detector.adapters.jsonl_store import JsonlTranscriptStore
from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    SystemEvent,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
)


def _transcript(transcript_id: str = "session-1") -> Transcript:
    return Transcript(
        TranscriptHeader(
            transcript_id,
            "dsh",
            "/logs/session.v3.jsonl",
            model="gpt-5.6-terra",
            provider="openai-codex",
            cwd="/tmp/project",
            created_at=1789756882954,
        ),
        (
            SystemEvent(7, 1, 1, "You are a coding agent."),
            UserEvent(8, 1, "liste les fichiers – s'il te plaît", "human"),
            UserEvent(9, 1, "runtime context", "harness"),
            AssistantEvent(
                15,
                1,
                1,
                "I'll list them.",
                (ToolCall("c1", "bash", '{"command":"ls"}'),),
                "toolUse",
            ),
            ToolResultEvent(17, 1, 1, "c1", "bash", "a.py\nb.py", False),
            AssistantEvent(20, 1, 2, "There are two files.", (), "stop"),
            TurnEndEvent(22, 1, "completed"),
        ),
    )


def test_save_writes_one_file_named_after_the_transcript(tmp_path):
    path = JsonlTranscriptStore().save(_transcript(), tmp_path / "out")
    assert path == tmp_path / "out" / "session-1.jsonl"
    assert path.exists()


def test_saved_file_starts_with_the_header_then_one_line_per_event(tmp_path):
    path = JsonlTranscriptStore().save(_transcript(), tmp_path)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["kind"] == "transcript"
    assert records[0]["transcript_id"] == "session-1"
    assert [r["kind"] for r in records[1:]] == [
        "system",
        "user",
        "user",
        "assistant",
        "tool_result",
        "assistant",
        "turn_end",
    ]


def test_save_then_load_round_trips(tmp_path):
    store = JsonlTranscriptStore()
    path = store.save(_transcript(), tmp_path)
    assert store.load(path) == _transcript()


def test_non_ascii_text_is_written_unescaped(tmp_path):
    path = JsonlTranscriptStore().save(_transcript(), tmp_path)
    assert "s'il te plaît" in path.read_text(encoding="utf-8")


def test_save_overwrites_a_previous_file(tmp_path):
    store = JsonlTranscriptStore()
    store.save(_transcript(), tmp_path)
    path = store.save(Transcript(_transcript().header, ()), tmp_path)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_load_tolerates_blank_lines(tmp_path):
    store = JsonlTranscriptStore()
    path = store.save(_transcript(), tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert store.load(path) == _transcript()


def test_load_without_a_header_raises(tmp_path):
    path = tmp_path / "headerless.jsonl"
    path.write_text(
        '{"kind": "user", "seq": 1, "turn": 1, "text": "hi", "origin": "human"}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="header"):
        JsonlTranscriptStore().load(path)


def test_load_of_an_empty_file_raises(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        JsonlTranscriptStore().load(path)


def test_load_many_keeps_the_given_order(tmp_path):
    store = JsonlTranscriptStore()
    second = store.save(_transcript("session-2"), tmp_path)
    first = store.save(_transcript("session-1"), tmp_path)
    assert [t.transcript_id for t in store.load_many([second, first])] == ["session-2", "session-1"]
