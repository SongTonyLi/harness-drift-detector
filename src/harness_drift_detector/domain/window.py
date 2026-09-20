"""Windows: the unit of judgment.

One window per assistant step, carrying only the context a judge needs. Sizes are bounded
by a Budget so that state stays small (System One models lose accuracy on large state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .transcript import Transcript

OMITTED_MARKER = "[... {n} chars omitted ...]"


@dataclass(frozen=True)
class Budget:
    user_request: int = 4000
    tool_result_head: int = 1600
    tool_result_tail: int = 800
    previous_assistant_text: int = 2000
    assistant_text: int = 4000
    arguments: int = 1200


def truncate(text: str, head: int, tail: int = 0) -> str:
    """Keep the first `head` and last `tail` chars; put OMITTED_MARKER (with the number of
    omitted chars) between them. Return `text` unchanged when it fits in head + tail."""
    raise NotImplementedError


@dataclass(frozen=True)
class ToolOutcome:
    tool: str
    is_error: bool
    text: str


@dataclass(frozen=True)
class PreviousMessage:
    """What the step is directly responding to."""

    source: Literal["user", "tools"]
    text: str = ""  # when source == "user"
    results: tuple[ToolOutcome, ...] = ()  # when source == "tools"


@dataclass(frozen=True)
class StepCall:
    tool: str
    arguments: str


@dataclass(frozen=True)
class Window:
    transcript_id: str
    turn: int
    step: int
    seq: int  # seq of the assistant event
    user_request: str
    previous_message: PreviousMessage
    previous_assistant_text: str
    assistant_text: str
    tool_calls: tuple[StepCall, ...] = ()
    ends_turn: bool = False

    @property
    def window_id(self) -> str:
        return f"{self.transcript_id}:t{self.turn}:s{self.step}"

    def to_state(self) -> dict[str, Any]:
        """JSON state handed to a Judge. Exact shape:

        {
          "user_request": str,
          "previous_message": {"from": "user", "text": str}
                              | {"from": "tools", "results": [{"tool","is_error","text"}]},
          "previous_assistant_text": str,
          "assistant_step": {"text": str, "tool_calls": [{"tool","arguments"}], "ends_turn": bool}
        }
        """
        raise NotImplementedError


def build_windows(transcript: Transcript, budget: Budget = Budget()) -> list[Window]:
    """One Window per AssistantEvent, in seq order.

    - user_request: text of the latest UserEvent with origin == "human" before the step
      (already truncated to budget.user_request). Harness-injected user messages are ignored.
    - previous_message: for the first assistant step of a turn, {"user", text of the latest
      human message}. For later steps, {"tools", results of the previous assistant step's
      tool calls in this turn} (each text truncated head/tail). If the previous step made no
      tool calls (text only), previous_message is the previous assistant text as
      PreviousMessage(source="user", text=<that text>)? No: use source="tools" with empty
      results only if calls existed but produced no result; otherwise fall back to the
      latest human message. Keep it literal: previous_message describes the last thing that
      happened before this step.
    - previous_assistant_text: text of the previous assistant step in the same turn ("" for
      the first step), truncated.
    - assistant_text: this step's text, truncated. tool_calls: this step's calls with
      arguments truncated (head only).
    - ends_turn: True when no later AssistantEvent exists in the same turn.
    """
    raise NotImplementedError
