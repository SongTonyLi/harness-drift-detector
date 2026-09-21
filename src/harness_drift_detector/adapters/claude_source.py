"""Claude Code session logs -> canonical Transcripts.

Layout: `<root>/<session-uuid>.jsonl` where `<root>` is `~/.claude/projects/<encoded-cwd>`.
One JSON record per line; `type` names the record kind. Subagent transcripts under
`<root>/<session-uuid>/subagents/` are separate conversations and are not read.

What survives: the user's prompts (typed, sent through the SDK, or queued while the
assistant worked), assistant messages with their tool calls, tool results, and turn ends.
User records the harness injected (skill bodies, compaction summaries, task notifications,
local-command output) keep origin "harness". Thinking blocks, attachments other than queued
prompts, hook records, and session bookkeeping records are dropped.

A response streams as several records sharing `message.id`, one content block each, and the
results of parallel tool calls interleave with them; the records of one id become one
assistant step. Records are read in file order: a branch the user rewound stays in the file
and is judged like any other step. A turn ends with the harness's `turn_duration` record
(completed), a `[Request interrupted by user]` message (aborted), or a synthetic assistant
message reporting an API error (error). Logs from older versions carry no `turn_duration`;
there a turn whose last step stopped with `end_turn` is completed when the next prompt
arrives or the log ends.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.transcript import (
    AssistantEvent,
    Event,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
)
from .scrub import clean

INTERRUPT_PREFIX = "[Request interrupted by user"
SYNTHETIC_MODEL = "<synthetic>"
API_ERROR_PREFIX = "API Error"
IMAGE_PLACEHOLDER = "[image]"

_COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
_COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)


def read_session_file(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            yield line.rstrip("\n")


def _content_text(content: Any) -> str:
    """Text of a message or tool-result content: a string, or text blocks joined by newlines
    with an image block shown as a placeholder."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif block.get("type") == "image":
            parts.append(IMAGE_PLACEHOLDER)
    return "\n".join(parts)


def normalize_command(text: str) -> str:
    """`<command-name>/x</command-name> ... <command-args>y</command-args>` -> `/x y`."""
    name = _COMMAND_NAME_RE.search(text)
    if name is None or not text.lstrip().startswith("<command-"):
        return text
    args = _COMMAND_ARGS_RE.search(text)
    return f"{name.group(1).strip()} {args.group(1).strip() if args else ''}".strip()


def _epoch_ms(timestamp: Any) -> int | None:
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


@dataclass
class _Step:
    """An assistant message being assembled from its streamed records."""

    message_id: str
    seq: int
    turn: int
    step: int
    text: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    model: str | None = None


@dataclass
class _Parser:
    source_path: str
    scrub: bool
    events: list[Event] = field(default_factory=list)
    turn: int = 1
    step: int = 0
    turn_has_steps: bool = False
    turn_ended: bool = False
    current: _Step | None = None
    last_stop_reason: str | None = None  # of the most recently closed assistant step
    last_seq: int = 0
    call_steps: dict[str, tuple[int, str]] = field(default_factory=dict)  # id -> (step, name)
    model: str | None = None
    cwd: str | None = None
    created_at: int | None = None

    def feed(self, seq: int, record: dict[str, Any]) -> None:
        if record.get("isSidechain"):
            return
        self.last_seq = seq
        self.cwd = self.cwd or _opt_str(record.get("cwd"))
        if self.created_at is None:
            self.created_at = _epoch_ms(record.get("timestamp"))
        match record.get("type"):
            case "user":
                self._user(seq, record)
            case "assistant":
                self._assistant(seq, record)
            case "system":
                if record.get("subtype") == "turn_duration":
                    self._end_turn(seq, "completed")
            case "attachment":
                attachment = record.get("attachment")
                if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
                    self._queued(seq, attachment)
            case _:
                return

    def finish(self) -> list[Event]:
        self._flush()
        self._complete_if_assistant_stopped(self.last_seq + 1)
        return sorted(self.events, key=lambda event: event.seq)

    # -- user records ---------------------------------------------------------------------

    def _user(self, seq: int, record: dict[str, Any]) -> None:
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        results = [
            block
            for block in (content if isinstance(content, list) else [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        if results:
            for block in results:
                self._tool_result(seq, block)
            return
        text = _content_text(content)
        if text.lstrip().startswith(INTERRUPT_PREFIX):
            self._end_turn(seq, "aborted")
            return
        origin = record.get("origin")
        human = (
            isinstance(origin, dict)
            and origin.get("kind") == "human"
            and not record.get("isMeta")
            and not record.get("isCompactSummary")
        )
        if human:
            self._start_turn_if_needed(seq)
        self.events.append(
            UserEvent(
                seq=seq,
                turn=self.turn,
                text=clean(normalize_command(text), self.scrub),
                origin="human" if human else "harness",
            )
        )

    def _queued(self, seq: int, attachment: dict[str, Any]) -> None:
        """Something delivered into the running turn. Only a prompt the person typed is human:
        the same queue carries task notifications (`commandMode` "task-notification", no
        `origin`) and the harness's own continuations, which are context, not a new request."""
        origin = attachment.get("origin")
        kind = origin.get("kind") if isinstance(origin, dict) else None
        human = kind == "human" and attachment.get("commandMode") == "prompt"
        text = _content_text(attachment.get("prompt"))
        if not text.strip():
            return
        self.events.append(
            UserEvent(
                seq=seq,
                turn=self.turn,
                text=clean(text, self.scrub),
                origin="human" if human else "harness",
            )
        )

    def _tool_result(self, seq: int, block: dict[str, Any]) -> None:
        call_id = str(block.get("tool_use_id", ""))
        step, name = self.call_steps.get(call_id, (self.step, ""))
        self.events.append(
            ToolResultEvent(
                seq=seq,
                turn=self.turn,
                step=step,
                call_id=call_id,
                name=name,
                text=clean(_content_text(block.get("content")), self.scrub),
                is_error=bool(block.get("is_error", False)),
            )
        )

    # -- assistant records ----------------------------------------------------------------

    def _assistant(self, seq: int, record: dict[str, Any]) -> None:
        message = record.get("message")
        if not isinstance(message, dict):
            return
        model = _opt_str(message.get("model"))
        content = message.get("content")
        blocks = (
            [block for block in content if isinstance(block, dict)]
            if isinstance(content, list)
            else []
        )
        if model == SYNTHETIC_MODEL:
            # Not model output: the harness's own placeholder ("No response requested.",
            # an API error, a usage limit). Only an API error says something about the turn.
            self._flush()
            if _content_text(blocks).startswith(API_ERROR_PREFIX):
                self._end_turn(seq, "error")
            return
        message_id = str(message.get("id", ""))
        if self.current is None or self.current.message_id != message_id:
            self._flush()
            self.step += 1
            self.turn_has_steps = True
            self.current = _Step(message_id, seq, self.turn, self.step, model=model)
            self.model = self.model or model
        step = self.current
        if message.get("stop_reason") is not None:
            step.stop_reason = str(message["stop_reason"])
        for block in blocks:
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                step.text.append(str(block["text"]))
            elif kind == "tool_use":
                call = ToolCall(
                    call_id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=clean(
                        json.dumps(
                            block.get("input", {}), ensure_ascii=False, separators=(",", ":")
                        ),
                        self.scrub,
                    ),
                )
                step.calls.append(call)
                self.call_steps[call.call_id] = (step.step, call.name)

    def _flush(self) -> None:
        step = self.current
        if step is None:
            return
        self.events.append(
            AssistantEvent(
                seq=step.seq,
                turn=step.turn,
                step=step.step,
                text=clean("\n".join(step.text), self.scrub),
                tool_calls=tuple(step.calls),
                stop_reason=step.stop_reason,
            )
        )
        self.last_stop_reason = step.stop_reason
        self.current = None

    # -- turns ----------------------------------------------------------------------------

    def _start_turn_if_needed(self, seq: int) -> None:
        """A human prompt opens a new turn once the current one has been used."""
        self._flush()
        self._complete_if_assistant_stopped(seq)
        if self.turn_has_steps or self.turn_ended:
            self.turn += 1
            self.step = 0
            self.turn_has_steps = False
            self.turn_ended = False

    def _complete_if_assistant_stopped(self, seq: int) -> None:
        """Older logs carry no `turn_duration` record. A turn whose last step stopped with
        `end_turn` ended by the assistant's choice, so it is completed once the next prompt
        arrives or the log ends; a turn left at `tool_use` stays unended."""
        if self.turn_has_steps and not self.turn_ended and self.last_stop_reason == "end_turn":
            self._end_turn(seq, "completed")

    def _end_turn(self, seq: int, reason: str) -> None:
        self._flush()
        if self.turn_ended:
            return
        self.turn_ended = True
        self.events.append(TurnEndEvent(seq=seq, turn=self.turn, reason=reason))


def _opt_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def parse_claude_lines(lines: Iterable[str], source_path: str, scrub: bool = True) -> Transcript:
    """Parse the lines of one Claude Code session log. Raises ValueError on a malformed log
    or one that holds no conversation."""
    parser = _Parser(source_path=source_path, scrub=scrub)
    records = 0
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
        records += 1
        parser.feed(lineno, record)
    if records == 0:
        raise ValueError(f"{source_path}: empty log, no records")
    events = parser.finish()
    header = TranscriptHeader(
        transcript_id=Path(source_path).stem,
        harness="claude",
        source_path=source_path,
        model=parser.model,
        provider=None,
        cwd=parser.cwd,
        created_at=parser.created_at,
    )
    return Transcript(header=header, events=tuple(events))


class ClaudeSessionSource:
    """TranscriptSource over a Claude Code project directory
    (`~/.claude/projects/<encoded-cwd>`)."""

    harness = "claude"

    def __init__(self, root: Path, scrub: bool = True) -> None:
        self.root = Path(root)
        self.scrub = scrub

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(path.stem for path in self.root.glob("*.jsonl") if path.is_file())

    def load(self, transcript_id: str) -> Transcript:
        path = self.root / f"{transcript_id}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"no Claude Code session log at {path}")
        return parse_claude_lines(read_session_file(path), str(path), scrub=self.scrub)
