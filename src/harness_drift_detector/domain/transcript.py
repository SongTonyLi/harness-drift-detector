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
        return sorted({event.turn for event in self.events})

    def assistant_steps(self) -> list[AssistantEvent]:
        """All assistant events in seq order."""
        steps = [event for event in self.events if isinstance(event, AssistantEvent)]
        return sorted(steps, key=lambda event: event.seq)


def header_to_record(header: TranscriptHeader) -> dict[str, Any]:
    """Canonical JSONL header line as a dict (key order: kind, transcript_id, harness, ...)."""
    return {
        "kind": "transcript",
        "transcript_id": header.transcript_id,
        "harness": header.harness,
        "source_path": header.source_path,
        "model": header.model,
        "provider": header.provider,
        "cwd": header.cwd,
        "created_at": header.created_at,
    }


def event_to_record(event: Event) -> dict[str, Any]:
    """Canonical JSONL event line as a dict. `kind` is the first key.

    assistant: {"kind","seq","turn","step","text","tool_calls":[{"call_id","name","arguments"}],"stop_reason"}
    tool_result: {"kind","seq","turn","step","call_id","name","text","is_error"}
    user: {"kind","seq","turn","text","origin"}
    system: {"kind","seq","turn","step","text"}
    turn_end: {"kind","seq","turn","reason"}
    """
    if isinstance(event, SystemEvent):
        return {
            "kind": "system",
            "seq": event.seq,
            "turn": event.turn,
            "step": event.step,
            "text": event.text,
        }
    if isinstance(event, UserEvent):
        return {
            "kind": "user",
            "seq": event.seq,
            "turn": event.turn,
            "text": event.text,
            "origin": event.origin,
        }
    if isinstance(event, AssistantEvent):
        return {
            "kind": "assistant",
            "seq": event.seq,
            "turn": event.turn,
            "step": event.step,
            "text": event.text,
            "tool_calls": [
                {"call_id": call.call_id, "name": call.name, "arguments": call.arguments}
                for call in event.tool_calls
            ],
            "stop_reason": event.stop_reason,
        }
    if isinstance(event, ToolResultEvent):
        return {
            "kind": "tool_result",
            "seq": event.seq,
            "turn": event.turn,
            "step": event.step,
            "call_id": event.call_id,
            "name": event.name,
            "text": event.text,
            "is_error": event.is_error,
        }
    if isinstance(event, TurnEndEvent):
        return {
            "kind": "turn_end",
            "seq": event.seq,
            "turn": event.turn,
            "reason": event.reason,
        }
    raise ValueError(f"unknown event type: {type(event).__name__}")


def record_to_header(record: dict[str, Any]) -> TranscriptHeader:
    """Inverse of header_to_record. Raises ValueError if kind != "transcript"."""
    kind = record.get("kind")
    if kind != "transcript":
        raise ValueError(f"expected a transcript header, got kind={kind!r}")
    return TranscriptHeader(
        transcript_id=record["transcript_id"],
        harness=record["harness"],
        source_path=record["source_path"],
        model=record.get("model"),
        provider=record.get("provider"),
        cwd=record.get("cwd"),
        created_at=record.get("created_at"),
    )


def record_to_event(record: dict[str, Any]) -> Event:
    """Inverse of event_to_record. Raises ValueError on unknown kind."""
    kind = record.get("kind")
    if kind == "system":
        return SystemEvent(
            seq=record["seq"], turn=record["turn"], step=record["step"], text=record["text"]
        )
    if kind == "user":
        return UserEvent(
            seq=record["seq"],
            turn=record["turn"],
            text=record["text"],
            origin=record.get("origin", "human"),
        )
    if kind == "assistant":
        return AssistantEvent(
            seq=record["seq"],
            turn=record["turn"],
            step=record["step"],
            text=record["text"],
            tool_calls=tuple(
                ToolCall(call["call_id"], call["name"], call["arguments"])
                for call in record.get("tool_calls") or ()
            ),
            stop_reason=record.get("stop_reason"),
        )
    if kind == "tool_result":
        return ToolResultEvent(
            seq=record["seq"],
            turn=record["turn"],
            step=record["step"],
            call_id=record["call_id"],
            name=record["name"],
            text=record["text"],
            is_error=bool(record.get("is_error", False)),
        )
    if kind == "turn_end":
        return TurnEndEvent(seq=record["seq"], turn=record["turn"], reason=record["reason"])
    raise ValueError(f"unknown event kind: {kind!r}")
