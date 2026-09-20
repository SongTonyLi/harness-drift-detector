"""A Judge with scripted answers, for tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence

from ..domain.judgment import JudgeResult, Judgment, Usage
from ..domain.probes import Probe
from ..domain.transcript import JsonValue

Answers = Mapping[str, float] | Callable[[JsonValue, Sequence[Probe]], Mapping[str, float]]


class FakeJudge:
    """Answers every requested probe from `answers` (missing probes answer 0.0).

    Every call is appended to `calls` as `(state, tuple of probe ids)`. `fail_when` turns a
    call into a RuntimeError, `delay_s` makes the call await, and `max_concurrent` records
    the high-water mark of overlapping calls so concurrency limits can be asserted.
    """

    def __init__(
        self,
        answers: Answers,
        model: str = "fake",
        name: str = "fake",
        fail_when: Callable[[JsonValue], bool] | None = None,
        delay_s: float = 0.0,
        usage: Usage = Usage(),
    ) -> None:
        self.answers = answers
        self.model = model
        self.name = name
        self.fail_when = fail_when
        self.delay_s = delay_s
        self.usage = usage
        self.calls: list[tuple[JsonValue, tuple[str, ...]]] = []
        self.concurrent = 0
        self.max_concurrent = 0

    async def judge(self, state: JsonValue, probes: Sequence[Probe]) -> JudgeResult:
        self.calls.append((state, tuple(probe.id for probe in probes)))
        if self.fail_when is not None and self.fail_when(state):
            raise RuntimeError("FakeJudge failure")
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
        finally:
            self.concurrent -= 1
        answers = self.answers(state, probes) if callable(self.answers) else self.answers
        judgments = {
            probe.id: Judgment(probe_id=probe.id, probability=float(answers.get(probe.id, 0.0)))
            for probe in probes
        }
        return JudgeResult(judgments=judgments, model=self.model, usage=self.usage)
