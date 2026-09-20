"""TypeSafe (Jev) implementation of the Judge port."""

from __future__ import annotations

import time
from typing import Any, Sequence

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria, Score

from ..domain.judgment import JudgeResult, Judgment, Usage
from ..domain.probes import Probe, ScoreProbe
from ..domain.transcript import JsonValue

DEFAULT_MODEL = "jev-latest"


def probes_to_questions(probes: Sequence[Probe]) -> dict[str, Noul | Score]:
    """One System One question per probe, keyed by probe id."""
    questions: dict[str, Noul | Score] = {}
    for probe in probes:
        if isinstance(probe, ScoreProbe):
            questions[probe.id] = Score(instructions=probe.instructions, criteria=list(probe.levels))
        else:
            questions[probe.id] = Noul(
                instructions=probe.instructions,
                criteria=NoulCriteria(true=probe.true_criteria, false=probe.false_criteria),
            )
    return questions


def response_to_result(response: Any, probes: Sequence[Probe], latency_s: float) -> JudgeResult:
    """Answers -> judgments. A Noul's probability is its `noul`; a Score's is
    `score / (levels - 1)`, clipped to [0, 1]. Probes the model did not answer are dropped."""
    nouls = getattr(response, "nouls", {})
    scores = getattr(response, "scores", {})
    judgments: dict[str, Judgment] = {}
    for probe in probes:
        if isinstance(probe, ScoreProbe):
            answer = scores.get(probe.id)
            if answer is None:
                continue
            span = max(len(probe.levels) - 1, 1)
            judgments[probe.id] = Judgment(
                probe_id=probe.id,
                probability=min(1.0, max(0.0, answer.score / span)),
                confidence=answer.confidence,
                raw={
                    "score": answer.score,
                    "probabilities": {str(level): p for level, p in answer.probabilities.items()},
                },
            )
        else:
            answer = nouls.get(probe.id)
            if answer is None:
                continue
            judgments[probe.id] = Judgment(
                probe_id=probe.id,
                probability=answer.noul,
                confidence=None,
                raw={"noul": answer.noul},
            )
    return JudgeResult(
        judgments=judgments,
        model=getattr(response, "model", ""),
        usage=_usage(getattr(response, "usage", None)),
        latency_s=latency_s,
    )


def _usage(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )


class TypeSafeJudge:
    """Asks every probe for one window in a single System One call.

    The client reads TYPESAFE_API_KEY from the environment and raises TypeSafeError when it
    is missing; the key is never stored or logged here.
    """

    name = "typesafe"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
        client: AsyncTypeSafeClient | None = None,
    ) -> None:
        self.model = model
        self._client = client if client is not None else AsyncTypeSafeClient(timeout=timeout)

    async def judge(self, state: JsonValue, probes: Sequence[Probe]) -> JudgeResult:
        questions = probes_to_questions(probes)
        started = time.perf_counter()
        response = await self._client.system_one(state=state, questions=questions, model=self.model)
        return response_to_result(response, probes, time.perf_counter() - started)

    async def aclose(self) -> None:
        await self._client.aclose()
