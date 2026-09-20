"""DeepSeek Harness (`dsh`) session logs -> canonical Transcripts.

Layout: `<root>/session-<uuid>/session.v3.jsonl` (raw) or `session.v3.jsonl.zstd`
(concatenated Zstandard frames, one per append). The raw file wins when both exist.

Only the parts a judge needs survive: system/user/assistant messages, tool calls and
their results, and turn boundaries. Provider replay state, reasoning blocks, request
headers and unknown event types are dropped.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from ..domain.transcript import (
    AssistantEvent,
    Event,
    SystemEvent,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
)
from .scrub import clean

RAW_NAME = "session.v3.jsonl"
ZSTD_NAME = "session.v3.jsonl.zstd"


def session_file(directory: Path) -> Path | None:
    """The v3 log inside one session directory, preferring the uncompressed file."""
    for name in (RAW_NAME, ZSTD_NAME):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def read_v3_file(path: Path) -> Iterator[str]:
    """Yield the lines of a raw or zstd-compressed v3 log."""
    if path.name.endswith(".zstd"):
        import zstandard

        with path.open("rb") as handle:
            reader = zstandard.ZstdDecompressor().stream_reader(handle, read_across_frames=True)
            with io.TextIOWrapper(reader, encoding="utf-8") as text:
                for line in text:
                    yield line.rstrip("\n")
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            yield line.rstrip("\n")


def _text_of(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    parts = [
        block["text"]
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    ]
    return "\n".join(parts)


def _tool_calls_of(blocks: Any, scrub: bool) -> tuple[ToolCall, ...]:
    if not isinstance(blocks, list):
        return ()
    calls = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool-call":
            calls.append(
                ToolCall(
                    call_id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=clean(str(block.get("arguments", "")), scrub),
                )
            )
    return tuple(calls)


def _stop_reason_of(message: dict[str, Any]) -> str | None:
    source = message.get("source")
    if not isinstance(source, dict):
        return None
    replay = source.get("replayState")
    if not isinstance(replay, dict):
        return None
    response = replay.get("response")
    if not isinstance(response, dict):
        return None
    reason = response.get("stopReason")
    return str(reason) if reason is not None else None


def parse_v3_lines(lines: Iterable[str], source_path: str, scrub: bool = True) -> Transcript:
    """Parse the lines of a v3 session log. Raises ValueError on a malformed log."""
    session: dict[str, Any] | None = None
    events: list[Event] = []
    call_names: dict[str, str] = {}
    turn = 1
    model: str | None = None
    provider: str | None = None

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source_path}: line {lineno} is not valid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{source_path}: line {lineno} is not a JSON object")

        event_type = record.get("type")
        if session is None:
            if event_type != "session":
                raise ValueError(
                    f"{source_path}: line {lineno} is {event_type!r}, expected a `session` header"
                )
            if record.get("version") != 3:
                raise ValueError(
                    f"{source_path}: unsupported session version {record.get('version')!r}"
                )
            session = record
            continue

        data = record.get("data")
        data = data if isinstance(data, dict) else {}
        seq = int(record.get("seq", 0))
        message = data.get("message")
        message = message if isinstance(message, dict) else {}

        match event_type:
            case "turn/start":
                turn = int(data.get("turn", turn))
            case "request/context":
                model = model or _opt_str(data.get("model"))
                provider = provider or _opt_str(data.get("provider"))
            case "request/header":
                header = data.get("header")
                config = header.get("config") if isinstance(header, dict) else None
                if isinstance(config, dict):
                    model = model or _opt_str(config.get("model"))
                    provider = provider or _opt_str(config.get("provider"))
            case "system/message":
                events.append(
                    SystemEvent(
                        seq=seq,
                        turn=int(data.get("turn", turn)),
                        step=int(data.get("step", 1)),
                        text=clean(_text_of(message.get("content")), scrub),
                    )
                )
            case "user/message":
                source = data.get("source")
                kind = source.get("kind") if isinstance(source, dict) else None
                events.append(
                    UserEvent(
                        seq=seq,
                        turn=int(data.get("turn", turn)),
                        text=clean(_text_of(data.get("content")), scrub),
                        origin="human" if kind == "user" else "harness",
                    )
                )
            case "assistant/message":
                content = message.get("content")
                calls = _tool_calls_of(content, scrub)
                for call in calls:
                    call_names[call.call_id] = call.name
                events.append(
                    AssistantEvent(
                        seq=seq,
                        turn=int(data.get("turn", turn)),
                        step=int(data.get("step", 1)),
                        text=clean(_text_of(content), scrub),
                        tool_calls=calls,
                        stop_reason=_stop_reason_of(message),
                    )
                )
            case "tool/call":
                call_id = str(data.get("callId", ""))
                if call_id:
                    call_names[call_id] = str(data.get("name", call_names.get(call_id, "")))
            case "tool/result":
                events.extend(_tool_results(seq, data, message, turn, call_names, scrub))
            case "turn/end":
                reason = data.get("reason")
                if isinstance(reason, dict):
                    reason_text = str(reason.get("kind", ""))
                else:
                    reason_text = "" if reason is None else str(reason)
                events.append(
                    TurnEndEvent(seq=seq, turn=int(data.get("turn", turn)), reason=reason_text)
                )
            case _:
                continue

    if session is None:
        raise ValueError(f"{source_path}: empty log, no `session` header")

    header = TranscriptHeader(
        transcript_id=str(session.get("id") or Path(source_path).parent.name),
        harness="dsh",
        source_path=source_path,
        model=model,
        provider=provider,
        cwd=_opt_str(session.get("cwd")),
        created_at=session.get("createdAt") if isinstance(session.get("createdAt"), int) else None,
    )
    return Transcript(header=header, events=tuple(events))


def _opt_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _tool_results(
    seq: int,
    data: dict[str, Any],
    message: dict[str, Any],
    turn: int,
    call_names: dict[str, str],
    scrub: bool,
) -> list[ToolResultEvent]:
    source = message.get("source")
    fallback_id = source.get("callId") if isinstance(source, dict) else None
    blocks = message.get("content")
    results: list[ToolResultEvent] = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool-result":
            continue
        call_id = str(block.get("toolCallId") or fallback_id or "")
        results.append(
            ToolResultEvent(
                seq=seq,
                turn=int(data.get("turn", turn)),
                step=int(data.get("step", 1)),
                call_id=call_id,
                name=str(block.get("toolName") or data.get("name") or call_names.get(call_id, "")),
                text=clean(_text_of(block.get("content")), scrub),
                is_error=bool(block.get("isError", False)),
            )
        )
    return results


class DshSessionSource:
    """TranscriptSource over a dsh sessions root (`~/.dsh/sessions/<encoded-cwd>`)."""

    harness = "dsh"

    def __init__(self, root: Path, scrub: bool = True) -> None:
        self.root = Path(root)
        self.scrub = scrub

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            directory.name
            for directory in self.root.iterdir()
            if directory.is_dir() and session_file(directory) is not None
        )

    def load(self, transcript_id: str) -> Transcript:
        directory = self.root / transcript_id
        path = session_file(directory)
        if path is None:
            raise FileNotFoundError(f"no v3 session log in {directory}")
        return parse_v3_lines(read_v3_file(path), str(path), scrub=self.scrub)
