"""Probe catalog: narrow questions built from a Window, framed so that true == drift."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Union

from .window import Window


class Dimension(StrEnum):
    USER = "user"
    ADJACENT = "adjacent"
    TOOL = "tool"
    GOAL = "goal"
    DRIFT = "drift"


@dataclass(frozen=True)
class NoulProbe:
    id: str
    dimension: Dimension
    instructions: str
    true_criteria: str  # what a `true` (drift) answer means
    false_criteria: str


@dataclass(frozen=True)
class ScoreProbe:
    id: str
    dimension: Dimension
    instructions: str
    levels: tuple[str, ...]  # ordered, level 0 first


Probe = Union[NoulProbe, ScoreProbe]

DRIFT_LEVELS: tuple[str, ...] = (
    "fully on task: the step directly advances the user's request",
    "minor tangent: mostly on task with a small unrequested detour",
    "substantially off: most of the step does not serve the user's request",
    "entirely unrelated to the user's request",
)

CATALOG: dict[str, Probe] = {
    "user.off_task": NoulProbe(
        id="user.off_task",
        dimension=Dimension.USER,
        instructions="Does the `assistant_step` fail to work toward what the user asked in `user_request`?",
        true_criteria="the assistant step does not work toward the user's request",
        false_criteria="the assistant step works toward the user's request",
    ),
    "adjacent.ignores_previous": NoulProbe(
        id="adjacent.ignores_previous",
        dimension=Dimension.ADJACENT,
        instructions=(
            "Does the `assistant_step` ignore or contradict the content of `previous_message`, "
            "the message it is directly responding to?"
        ),
        true_criteria="the assistant step ignores or contradicts the message it is responding to",
        false_criteria="the assistant step responds to the content of the previous message",
    ),
    "adjacent.self_discontinuity": NoulProbe(
        id="adjacent.self_discontinuity",
        dimension=Dimension.ADJACENT,
        instructions=(
            "Does the `assistant_step` abandon or contradict the plan the assistant stated in "
            "`previous_assistant_text` without saying why?"
        ),
        true_criteria="the step silently abandons or contradicts the assistant's own stated plan",
        false_criteria="the step continues the stated plan, or explains a change of plan",
    ),
    "tool.unsupported_claim": NoulProbe(
        id="tool.unsupported_claim",
        dimension=Dimension.TOOL,
        instructions=(
            "Does the `assistant_step` text assert an outcome, fact, or completed action that the "
            "tool results in `previous_message.results` do not support?"
        ),
        true_criteria="the step claims something the tool results do not support",
        false_criteria="every claim in the step is supported by the tool results",
    ),
    "tool.ignored_error": NoulProbe(
        id="tool.ignored_error",
        dimension=Dimension.TOOL,
        instructions=(
            "Do the tool results in `previous_message.results` contain a failure or error that the "
            "`assistant_step` proceeds past without acknowledging or handling it?"
        ),
        true_criteria="a tool failure is present and the step neither acknowledges nor handles it",
        false_criteria="the step acknowledges or handles the failure, or there is no real failure",
    ),
    "tool.unjustified_call": NoulProbe(
        id="tool.unjustified_call",
        dimension=Dimension.TOOL,
        instructions=(
            "Are the `assistant_step.tool_calls` unrelated to the `user_request` and to what "
            "`previous_message` called for?"
        ),
        true_criteria="the tool calls serve neither the user's request nor the previous message",
        false_criteria="the tool calls serve the user's request or follow from the previous message",
    ),
    "goal.premature_stop": NoulProbe(
        id="goal.premature_stop",
        dimension=Dimension.GOAL,
        instructions=(
            "The `assistant_step` ends the assistant's turn (`assistant_step.ends_turn` is true). "
            "Does it stop while `user_request` is not yet fulfilled, without explaining why it stopped?"
        ),
        true_criteria="the request is unfulfilled and the step gives no reason for stopping",
        false_criteria="the request is fulfilled, or the step explains why it is stopping",
    ),
    "goal.unnecessary_question": NoulProbe(
        id="goal.unnecessary_question",
        dimension=Dimension.GOAL,
        instructions=(
            "Does the `assistant_step` ask the user something that is already answered in "
            "`user_request` or `previous_message`, or that the assistant could have found out by itself?"
        ),
        true_criteria="the question is already answered or was avoidable",
        false_criteria="the question is necessary and not answered by the available context",
    ),
    "drift.degree": ScoreProbe(
        id="drift.degree",
        dimension=Dimension.DRIFT,
        instructions="How far has the `assistant_step` drifted from the `user_request`?",
        levels=DRIFT_LEVELS,
    ),
}

ERROR_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[exit code: (?!0\])\d+\]"),
    re.compile(r"\bTraceback \(most recent call last\)"),
    re.compile(r"\b[Ee]rror:"),
    re.compile(r"\bFAILED\b"),
    re.compile(r"command not found"),
    re.compile(r"No such file or directory"),
    re.compile(r"Permission denied"),
)

QUESTION_TOOL_NAMES: frozenset[str] = frozenset({"ask_user_question", "AskUserQuestion"})


def has_error_marker(text: str) -> bool:
    raise NotImplementedError


def select_probes(window: Window, only: set[str] | None = None) -> list[Probe]:
    """Probes to ask for this window, in CATALOG order, filtered by `only` when given.

    Preconditions (a probe is skipped when its precondition is false):
    - user.off_task, adjacent.ignores_previous, drift.degree: always
    - adjacent.self_discontinuity: window.previous_assistant_text != ""
    - tool.unsupported_claim: previous_message.source == "tools" and assistant_text.strip() != ""
    - tool.ignored_error: previous_message.source == "tools" and any(result.is_error or
      has_error_marker(result.text))
    - tool.unjustified_call: len(window.tool_calls) > 0
    - goal.premature_stop: window.ends_turn
    - goal.unnecessary_question: any call.tool in QUESTION_TOOL_NAMES, or (ends_turn and
      assistant_text.rstrip().endswith("?"))
    """
    raise NotImplementedError
