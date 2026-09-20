from pathlib import Path

from harness_drift_detector.adapters.jsonl_store import JsonlTranscriptStore
from harness_drift_detector.application.convert import ConvertSessions, ConvertSummary
from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    Transcript,
    TranscriptHeader,
    UserEvent,
)


def _transcript(transcript_id: str) -> Transcript:
    return Transcript(
        TranscriptHeader(transcript_id, "stub", f"/logs/{transcript_id}"),
        (UserEvent(1, 1, "hi", "human"), AssistantEvent(2, 1, 1, "hello")),
    )


class StubSource:
    harness = "stub"

    def __init__(self, ids: list[str], broken: dict[str, Exception] | None = None) -> None:
        self._ids = ids
        self._broken = broken or {}
        self.loaded: list[str] = []

    def list_ids(self) -> list[str]:
        return list(self._ids)

    def load(self, transcript_id: str) -> Transcript:
        self.loaded.append(transcript_id)
        if transcript_id in self._broken:
            raise self._broken[transcript_id]
        if transcript_id == "session-empty":
            return Transcript(TranscriptHeader(transcript_id, "stub", "/logs/empty"), ())
        return _transcript(transcript_id)


class BrokenStore:
    def save(self, transcript: Transcript, directory: Path) -> Path:
        raise OSError("disk full")

    def load(self, path: Path) -> Transcript:  # pragma: no cover - unused
        raise NotImplementedError


def test_run_converts_every_listed_session(tmp_path):
    source = StubSource(["session-a", "session-b"])
    summary = ConvertSessions(source, JsonlTranscriptStore()).run(tmp_path / "out")
    assert isinstance(summary, ConvertSummary)
    assert summary.converted == [tmp_path / "out" / "session-a.jsonl", tmp_path / "out" / "session-b.jsonl"]
    assert summary.skipped == []
    assert all(path.exists() for path in summary.converted)


def test_run_restricts_to_the_given_ids(tmp_path):
    source = StubSource(["session-a", "session-b"])
    summary = ConvertSessions(source, JsonlTranscriptStore()).run(tmp_path, ids=["session-b"])
    assert source.loaded == ["session-b"]
    assert [path.name for path in summary.converted] == ["session-b.jsonl"]


def test_a_failing_session_is_skipped_and_the_batch_continues(tmp_path):
    source = StubSource(
        ["session-bad", "session-good"], broken={"session-bad": ValueError("line 3 is not valid JSON")}
    )
    summary = ConvertSessions(source, JsonlTranscriptStore()).run(tmp_path)
    assert [path.name for path in summary.converted] == ["session-good.jsonl"]
    assert len(summary.skipped) == 1
    skipped_id, reason = summary.skipped[0]
    assert skipped_id == "session-bad"
    assert "line 3 is not valid JSON" in reason


def test_a_store_failure_is_skipped_too(tmp_path):
    summary = ConvertSessions(StubSource(["session-a"]), BrokenStore()).run(tmp_path)
    assert summary.converted == []
    assert summary.skipped[0][0] == "session-a"
    assert "disk full" in summary.skipped[0][1]


def test_a_session_without_events_is_reported_as_skipped(tmp_path):
    summary = ConvertSessions(StubSource(["session-empty"]), JsonlTranscriptStore()).run(tmp_path)
    assert summary.converted == []
    assert summary.skipped == [("session-empty", "no events")]
    assert not (tmp_path / "session-empty.jsonl").exists()


def test_run_with_no_sessions_returns_an_empty_summary(tmp_path):
    summary = ConvertSessions(StubSource([]), JsonlTranscriptStore()).run(tmp_path)
    assert summary.converted == [] and summary.skipped == []
