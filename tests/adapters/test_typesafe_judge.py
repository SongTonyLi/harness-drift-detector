"""TypeSafeJudge: probe -> question translation and response -> judgment translation."""

import dataclasses

import pytest
from typesafe_sdk import Noul, Score, SystemOneResponse

from harness_drift_detector.adapters.typesafe_judge import (
    TypeSafeJudge,
    probes_to_questions,
    response_to_result,
)
from harness_drift_detector.domain.judgment import Usage
from harness_drift_detector.domain.probes import CATALOG, DRIFT_LEVELS

OFF_TASK = CATALOG["user.off_task"]
DEGREE = CATALOG["drift.degree"]
PROBES = [OFF_TASK, DEGREE]

STATE = {
    "user_request": "list the files",
    "previous_message": {"from": "user", "text": "list the files"},
    "previous_assistant_text": "",
    "assistant_step": {"text": "Here is a poem.", "tool_calls": [], "ends_turn": True},
}


def _response(**overrides) -> SystemOneResponse:
    payload = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 120, "output_tokens": 12},
        "answers": {
            "user.off_task": {"type": "noul", "noul": 0.82},
            "drift.degree": {
                "type": "score",
                "score": 2.0,
                "confidence": 0.7,
                "legend": dict(enumerate(DRIFT_LEVELS)),
                "probabilities": {0: 0.05, 1: 0.05, 2: 0.8, 3: 0.1},
            },
        },
    }
    payload.update(overrides)
    return SystemOneResponse.model_validate(payload)


class _FakeClient:
    def __init__(self, response: SystemOneResponse) -> None:
        self.response = response
        self.seen: list[tuple[object, dict, str | None]] = []
        self.closed = False

    async def system_one(self, state, questions, *, model=None):
        self.seen.append((state, dict(questions), model))
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def test_probes_to_questions_builds_noul_with_criteria():
    questions = probes_to_questions([OFF_TASK])

    noul = questions["user.off_task"]
    assert isinstance(noul, Noul)
    assert noul.instructions == OFF_TASK.instructions
    assert noul.criteria == {"true": OFF_TASK.true_criteria, "false": OFF_TASK.false_criteria}


def test_probes_to_questions_builds_score_with_levels():
    questions = probes_to_questions(PROBES)

    assert list(questions) == ["user.off_task", "drift.degree"]
    score = questions["drift.degree"]
    assert isinstance(score, Score)
    assert score.instructions == DEGREE.instructions
    assert list(score.criteria) == list(DRIFT_LEVELS)


def test_response_to_result_maps_noul_and_normalizes_score():
    result = response_to_result(_response(), PROBES, 1.5)

    off_task = result.judgments["user.off_task"]
    assert off_task.probability == 0.82
    assert off_task.confidence is None
    assert off_task.raw == {"noul": 0.82}

    degree = result.judgments["drift.degree"]
    assert degree.probability == pytest.approx(2.0 / 3.0)
    assert degree.confidence == 0.7
    assert degree.raw == {
        "score": 2.0,
        "probabilities": {"0": 0.05, "1": 0.05, "2": 0.8, "3": 0.1},
    }

    assert result.model == "jev-1.13.0"
    assert result.usage == Usage(120, 12)
    assert result.latency_s == 1.5
    assert result.cached is False


def test_response_to_result_skips_probes_without_an_answer():
    response = _response(answers={"user.off_task": {"type": "noul", "noul": 0.1}})

    result = response_to_result(response, PROBES, 0.1)

    assert set(result.judgments) == {"user.off_task"}


async def test_judge_passes_state_and_questions_and_measures_latency():
    client = _FakeClient(_response())
    judge = TypeSafeJudge(client=client)

    result = await judge.judge(STATE, PROBES)

    assert judge.name == "typesafe" and judge.model == "jev-latest"
    state, questions, model = client.seen[0]
    assert state == STATE
    assert list(questions) == ["user.off_task", "drift.degree"]
    assert model == "jev-latest"
    assert result.latency_s > 0
    assert result.judgments["user.off_task"].probability == 0.82


async def test_judge_uses_the_configured_model_and_closes_the_client():
    client = _FakeClient(_response())
    judge = TypeSafeJudge(model="jev-1.13.0", client=client)

    await judge.judge(STATE, [OFF_TASK])
    await judge.aclose()

    assert client.seen[0][2] == "jev-1.13.0"
    assert client.closed is True


def test_score_probe_with_reworded_levels_is_normalized_by_its_own_levels():
    two_level = dataclasses.replace(DEGREE, levels=("on task", "off task"))
    response = _response(
        answers={
            "drift.degree": {
                "type": "score",
                "score": 1.0,
                "confidence": 0.4,
                "legend": {0: "on task", 1: "off task"},
                "probabilities": {0: 0.0, 1: 1.0},
            }
        }
    )

    result = response_to_result(response, [two_level], 0.2)

    assert result.judgments["drift.degree"].probability == 1.0
