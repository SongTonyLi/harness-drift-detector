"""Transcript aggregate and its canonical record form.

A transcript is one harness session, normalized. The canonical JSONL format is part of
the ubiquitous language, so the record <-> event mapping lives here (pure functions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Union

JsonValue = Union[str, int, float, bool, None, list["JsonValue"], dict[str, "JsonValue"]]

UserOrigin = Literal["human", "harness"]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # raw JSON text as emitted by the model


@dataclass(frozen=True)
class SystemEvent:
    seq: int
    turn: int
    step: int
    text: str
    kind: Literal["system"] = "system"


@dataclass(frozen=True)
class UserEvent:
    seq: int
    turn: int
    text: str
    origin: UserOrigin
    kind: Literal["user"] = "user"


@dataclass(frozen=True)
class AssistantEvent:
    seq: int
    turn: int
    step: int
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = None
    kind: Literal["assistant"] = "assistant"


@dataclass(frozen=True)
class ToolResultEvent:
    seq: int
    turn: int
    step: int
    call_id: str
    name: str
    text: str
    is_error: bool = False
    kind: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class TurnEndEvent:
    seq: int
    turn: int
    reason: str
    kind: Literal["turn_end"] = "turn_end"


Event = Union[SystemEvent, UserEvent, AssistantEvent, ToolResultEvent, TurnEndEvent]


@dataclass(frozen=True)
class TranscriptHeader:
    transcript_id: str
    harness: str
    source_path: str
    model: str | None = None
    provider: str | None = None
    cwd: str | None = None
    created_at: int | None = None  # epoch milliseconds
    kind: Literal["transcript"] = "transcript"


@dataclass(frozen=True)
class Transcript:
    header: TranscriptHeader
    events: tuple[Event, ...] = field(default_factory=tuple)

    @property
    def transcript_id(self) -> str:
        return self.header.transcript_id

    def turn_numbers(self) -> list[int]:
        """Distinct turn numbers in ascending order."""
        raise NotImplementedError

    def assistant_steps(self) -> list[AssistantEvent]:
        """All assistant events in seq order."""
        raise NotImplementedError


def header_to_record(header: TranscriptHeader) -> dict[str, Any]:
    """Canonical JSONL header line as a dict (key order: kind, transcript_id, harness, ...)."""
    raise NotImplementedError


def event_to_record(event: Event) -> dict[str, Any]:
    """Canonical JSONL event line as a dict. `kind` is the first key.

    assistant: {"kind","seq","turn","step","text","tool_calls":[{"call_id","name","arguments"}],"stop_reason"}
    tool_result: {"kind","seq","turn","step","call_id","name","text","is_error"}
    user: {"kind","seq","turn","text","origin"}
    system: {"kind","seq","turn","step","text"}
    turn_end: {"kind","seq","turn","reason"}
    """
    raise NotImplementedError


def record_to_header(record: dict[str, Any]) -> TranscriptHeader:
    """Inverse of header_to_record. Raises ValueError if kind != "transcript"."""
    raise NotImplementedError


def record_to_event(record: dict[str, Any]) -> Event:
    """Inverse of event_to_record. Raises ValueError on unknown kind."""
    raise NotImplementedError
