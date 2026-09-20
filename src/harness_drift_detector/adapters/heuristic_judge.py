"""Offline lexical Judge: no network, no provider. Proves the port and gives a baseline."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from typing import Any

from ..domain.judgment import JudgeResult, Judgment
from ..domain.probes import Probe, has_error_marker
from ..domain.transcript import JsonValue

TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")

ACKNOWLEDGEMENTS: tuple[str, ...] = (
    "error",
    "fail",
    "failed",
    "denied",
    "not found",
    "retry",
    "could not",
    "couldn't",
    "unable",
    "exit code",
)

UNDECIDED = 0.5


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


class HeuristicJudge:
    """Scores a `Window.to_state()` payload with token overlap and error markers."""

    name = "heuristic"
    model = "lexical-v1"

    async def judge(self, state: JsonValue, probes: Sequence[Probe]) -> JudgeResult:
        started = time.perf_counter()
        payload: dict[str, Any] = state if isinstance(state, dict) else {}
        off_task = _off_task(payload)
        judgments: dict[str, Judgment] = {}
        for probe in probes:
            if probe.id == "tool.ignored_error":
                judgments[probe.id] = Judgment(probe.id, _ignored_error(payload))
            elif probe.id in ("user.off_task", "drift.degree"):
                judgments[probe.id] = Judgment(probe.id, off_task)
            else:
                judgments[probe.id] = Judgment(probe.id, UNDECIDED, confidence=0.0)
        return JudgeResult(
            judgments=judgments,
            model=self.model,
            latency_s=time.perf_counter() - started,
        )


def _step(state: dict[str, Any]) -> dict[str, Any]:
    step = state.get("assistant_step")
    return step if isinstance(step, dict) else {}


def _step_text(state: dict[str, Any]) -> str:
    return str(_step(state).get("text") or "")


def _previous_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    previous = state.get("previous_message")
    if not isinstance(previous, dict) or previous.get("from") != "tools":
        return []
    results = previous.get("results") or []
    return [r for r in results if isinstance(r, dict)]


def _ignored_error(state: dict[str, Any]) -> float:
    """0.9 for an unacknowledged tool failure, 0.1 when the step acknowledges it, 0.0 when
    the previous results contain no failure at all."""
    failed = any(
        bool(result.get("is_error")) or has_error_marker(str(result.get("text") or ""))
        for result in _previous_results(state)
    )
    if not failed:
        return 0.0
    text = _step_text(state).lower()
    return 0.1 if any(word in text for word in ACKNOWLEDGEMENTS) else 0.9


def _off_task(state: dict[str, Any]) -> float:
    """1 - Jaccard overlap between the request's tokens and the step's tokens (text plus
    tool call arguments). An empty step, or a state with no tokens at all, is undecided."""
    calls = _step(state).get("tool_calls") or []
    arguments = " ".join(str(c.get("arguments") or "") for c in calls if isinstance(c, dict))
    content = f"{_step_text(state)} {arguments}".strip()
    if not content:
        return UNDECIDED
    request_tokens = _tokens(str(state.get("user_request") or ""))
    step_tokens = _tokens(content)
    union = request_tokens | step_tokens
    if not union:
        return UNDECIDED
    overlap = len(request_tokens & step_tokens) / len(union)
    return min(1.0, max(0.0, 1.0 - overlap))
