"""Ports (interfaces) implemented by adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .judgment import JudgeResult
from .transcript import Transcript


class TranscriptSource(Protocol):
    """Reads sessions from a harness's native storage."""

    harness: str

    def list_ids(self) -> list[str]: ...

    def load(self, transcript_id: str) -> Transcript: ...


class TranscriptStore(Protocol):
    """Reads and writes canonical JSONL transcripts."""

    def save(self, transcript: Transcript, directory: Path) -> Path: ...

    def load(self, path: Path) -> Transcript: ...


class JudgmentCache(Protocol):
    def get(self, key: str) -> JudgeResult | None: ...

    def put(self, key: str, result: JudgeResult) -> None: ...
