"""Windows: the unit of judgment.

One window per assistant step, carrying only the context a judge needs. Sizes are bounded
by a Budget so that state stays small (System One models lose accuracy on large state).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .transcript import (
    AssistantEvent,
    ToolResultEvent,
    Transcript,
    UserEvent,
)

OMITTED_MARKER = "[... {n} chars omitted ...]"
KEPT_LINE_MARKER = "[... from the omitted middle ...] {line}"

# The end of a long step carries its conclusions and any closing question, so the step text
# budget is spent head and tail, like a tool result, instead of head only.
ASSISTANT_TEXT_TAIL = 800
# A failure line rescued from the omitted middle of a long tool result is itself bounded.
ERROR_LINE_CHARS = 200


@dataclass(frozen=True)
class Budget:
    user_request: int = 4000
    tool_result_head: int = 1600
    tool_result_tail: int = 800
    previous_assistant_text: int = 2000
    assistant_text: int = 4000
    arguments: int = 1200
    # A turn-ending step also sees earlier results of its turn: each bounded, total bounded.
    turn_evidence_result: int = 600
    turn_evidence_total: int = 6000


def truncate(text: str, head: int, tail: int = 0) -> str:
    """Keep the first `head` and last `tail` chars; put OMITTED_MARKER (with the number of
    omitted chars) between them. Return `text` unchanged when it fits in head + tail."""
    keep_head = max(head, 0)
    keep_tail = max(tail, 0)
    omitted = len(text) - keep_head - keep_tail
    if omitted <= 0:
        return text
    marker = OMITTED_MARKER.format(n=omitted)
    if keep_tail == 0:
        return text[:keep_head] + marker
    return text[:keep_head] + marker + text[-keep_tail:]


def _assistant_split(budget: Budget) -> tuple[int, int]:
    """Head and tail shares of the step text budget; their sum is the budget."""
    tail = min(ASSISTANT_TEXT_TAIL, max(budget.assistant_text, 0) // 4)
    return budget.assistant_text - tail, tail


@dataclass(frozen=True)
class ToolOutcome:
    tool: str
    is_error: bool
    text: str
    input: str = ""  # the call's arguments (the command), so output is read with its cause


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
class TurnResult:
    """An earlier tool result of the same turn, shown only to a turn-ending step."""

    step: int
    tool: str
    input: str
    is_error: bool
    text: str


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
    turn_evidence: tuple[TurnResult, ...] = ()  # earlier results of the turn; ends_turn only

    @property
    def window_id(self) -> str:
        return f"{self.transcript_id}:t{self.turn}:s{self.step}"

    def to_state(self) -> dict[str, Any]:
        """JSON state handed to a Judge. Exact shape:

        {
          "user_request": str,
          "previous_message": {"from": "user", "text": str}
                              | {"from": "tools", "results": [{"tool","input","is_error","text"}]},
          "previous_assistant_text": str,
          "assistant_step": {"text": str, "tool_calls": [{"tool","arguments"}], "ends_turn": bool},
          "turn_evidence": [{"step","tool","input","is_error","text"}]   # only when non-empty
        }
        """
        if self.previous_message.source == "user":
            previous: dict[str, Any] = {"from": "user", "text": self.previous_message.text}
        else:
            previous = {
                "from": "tools",
                "results": [
                    {"tool": r.tool, "input": r.input, "is_error": r.is_error, "text": r.text}
                    for r in self.previous_message.results
                ],
            }
        state: dict[str, Any] = {
            "user_request": self.user_request,
            "previous_message": previous,
            "previous_assistant_text": self.previous_assistant_text,
            "assistant_step": {
                "text": self.assistant_text,
                "tool_calls": [{"tool": c.tool, "arguments": c.arguments} for c in self.tool_calls],
                "ends_turn": self.ends_turn,
            },
        }
        if self.turn_evidence:
            state["turn_evidence"] = [
                {
                    "step": r.step,
                    "tool": r.tool,
                    "input": r.input,
                    "is_error": r.is_error,
                    "text": r.text,
                }
                for r in self.turn_evidence
            ]
        return state


def build_windows(transcript: Transcript, budget: Budget = Budget()) -> list[Window]:
    """One Window per AssistantEvent, in seq order.

    - user_request: text of the latest UserEvent with origin == "human" before the step
      (already truncated to budget.user_request). Harness-injected user messages are ignored.
    - previous_message: for the first assistant step of a turn, {"user", text of the latest
      human message}. For later steps whose previous step made tool calls, {"tools", that
      step's results, each with the call's input and its text truncated head/tail} (empty
      results when calls produced no result). After a text-only step, the latest human
      message again: previous_message is literally the last thing that happened before
      this step.
    - previous_assistant_text: text of the previous assistant step in the same turn ("" for
      the first step), truncated.
    - assistant_text: this step's text, truncated head and tail so the ending survives.
      tool_calls: this step's calls with arguments truncated (head only).
    - ends_turn: True when no later AssistantEvent exists in the same turn.
    - turn_evidence: for a turn-ending step only, the results of every earlier step of the
      turn except the previous step (whose results are already previous_message), most
      recent first while budget.turn_evidence_total lasts, in chronological order. A final
      summary claims things established across the turn, not only by the previous step.
    """
    events = sorted(transcript.events, key=lambda event: event.seq)
    text_head, text_tail = _assistant_split(budget)

    last_step_seq: dict[int, int] = {}
    for event in events:
        if isinstance(event, AssistantEvent):
            last_step_seq[event.turn] = max(last_step_seq.get(event.turn, event.seq), event.seq)

    windows: list[Window] = []
    latest_human = ""
    previous_assistant: AssistantEvent | None = None
    pending_results: list[ToolResultEvent] = []
    turn_history: list[tuple[AssistantEvent, tuple[ToolOutcome, ...]]] = []

    for event in events:
        if isinstance(event, UserEvent):
            if event.origin == "human":
                latest_human = event.text
            continue
        if isinstance(event, ToolResultEvent):
            pending_results.append(event)
            continue
        if not isinstance(event, AssistantEvent):
            continue

        if previous_assistant is not None and previous_assistant.turn != event.turn:
            previous_assistant = None
            turn_history = []

        user_request = truncate(latest_human, budget.user_request)
        ends_turn = event.seq == last_step_seq.get(event.turn)

        if previous_assistant is not None:
            previous_outcomes = (
                _results_for(previous_assistant, pending_results, budget)
                if previous_assistant.tool_calls
                else ()
            )
            turn_history.append((previous_assistant, previous_outcomes))

        if previous_assistant is None:
            previous_message = PreviousMessage(source="user", text=user_request)
            previous_assistant_text = ""
        elif previous_assistant.tool_calls:
            previous_message = PreviousMessage(source="tools", results=previous_outcomes)
            previous_assistant_text = truncate(
                previous_assistant.text, budget.previous_assistant_text
            )
        else:
            previous_message = PreviousMessage(source="user", text=user_request)
            previous_assistant_text = truncate(
                previous_assistant.text, budget.previous_assistant_text
            )

        windows.append(
            Window(
                transcript_id=transcript.transcript_id,
                turn=event.turn,
                step=event.step,
                seq=event.seq,
                user_request=user_request,
                previous_message=previous_message,
                previous_assistant_text=previous_assistant_text,
                assistant_text=truncate(event.text, text_head, text_tail),
                tool_calls=tuple(
                    StepCall(tool=call.name, arguments=truncate(call.arguments, budget.arguments))
                    for call in event.tool_calls
                ),
                ends_turn=ends_turn,
                turn_evidence=_turn_evidence(turn_history[:-1], budget) if ends_turn else (),
            )
        )

        previous_assistant = event
        pending_results = []

    return windows


def _results_for(
    step: AssistantEvent, results: list[ToolResultEvent], budget: Budget
) -> tuple[ToolOutcome, ...]:
    """Results of `step`'s tool calls, in call order, then same-step results with other ids."""
    call_names = {call.call_id: call.name for call in step.tool_calls}
    call_inputs = {
        call.call_id: truncate(call.arguments, budget.arguments) for call in step.tool_calls
    }
    matched = {
        result.call_id: result
        for result in results
        if result.turn == step.turn and result.call_id in call_names
    }
    ordered: list[ToolResultEvent] = [
        matched[call.call_id] for call in step.tool_calls if call.call_id in matched
    ]
    ordered += [
        result
        for result in results
        if result.turn == step.turn
        and result.call_id not in call_names
        and result.step == step.step
    ]
    return tuple(
        ToolOutcome(
            tool=result.name or call_names.get(result.call_id, ""),
            is_error=result.is_error,
            text=_result_text(result.text, budget),
            input=call_inputs.get(result.call_id, ""),
        )
        for result in ordered
    )


def _turn_evidence(
    history: list[tuple[AssistantEvent, tuple[ToolOutcome, ...]]], budget: Budget
) -> tuple[TurnResult, ...]:
    """Earlier results of the turn for a turn-ending step: most recent first while the total
    budget lasts (the first result is always kept), returned in chronological order. Each
    result text is re-budgeted head and tail to `budget.turn_evidence_result`."""
    per_result = max(budget.turn_evidence_result, 0)
    head = per_result - per_result // 3
    tail = per_result - head
    chosen: list[TurnResult] = []
    spent = 0
    for step, outcomes in reversed(history):
        for outcome in reversed(outcomes):
            text = truncate(outcome.text, head, tail)
            cost = len(text) + len(outcome.input)
            if chosen and spent + cost > budget.turn_evidence_total:
                return tuple(reversed(chosen))
            spent += cost
            chosen.append(
                TurnResult(
                    step=step.step,
                    tool=outcome.tool,
                    input=outcome.input,
                    is_error=outcome.is_error,
                    text=text,
                )
            )
    return tuple(reversed(chosen))


def _result_text(text: str, budget: Budget) -> str:
    """Budgeted result text that never hides a failure.

    A long result (a test run, a build log) can carry its failure in the middle, which the
    head/tail budget would drop: the judge would not see it and the `tool.ignored_error`
    precondition, which reads this text, would not fire. When that happens the first failing
    line is carried over into the budgeted text.
    """
    from .probes import has_error_marker  # local: probes imports this module

    shown = truncate(text, budget.tool_result_head, budget.tool_result_tail)
    if shown == text or has_error_marker(shown) or not has_error_marker(text):
        return shown
    line = next((line for line in text.splitlines() if has_error_marker(line)), "").strip()
    if not line:
        return shown
    return f"{shown}\n{KEPT_LINE_MARKER.format(line=truncate(line, ERROR_LINE_CHARS))}"
