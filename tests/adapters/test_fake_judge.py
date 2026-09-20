"""FakeJudge: scripted answers, recorded calls, optional failure and delay."""

import asyncio

import pytest

from harness_drift_detector.adapters.fake_judge import FakeJudge
from harness_drift_detector.domain.judgment import Usage
from harness_drift_detector.domain.probes import CATALOG

PROBES = [CATALOG["user.off_task"], CATALOG["drift.degree"]]
STATE = {"user_request": "list the files"}


async def test_one_judgment_per_probe_with_zero_default():
    judge = FakeJudge({"user.off_task": 0.9})

    result = await judge.judge(STATE, PROBES)

    assert judge.name == "fake" and judge.model == "fake"
    assert set(result.judgments) == {"user.off_task", "drift.degree"}
    assert result.judgments["user.off_task"].probability == 0.9
    assert result.judgments["user.off_task"].probe_id == "user.off_task"
    assert result.judgments["drift.degree"].probability == 0.0
    assert result.model == "fake"
    assert result.cached is False


async def test_custom_model_name_and_usage():
    judge = FakeJudge({}, model="fake-2", name="scripted", usage=Usage(11, 3))

    result = await judge.judge(STATE, PROBES)

    assert judge.name == "scripted" and judge.model == "fake-2"
    assert result.model == "fake-2"
    assert result.usage == Usage(11, 3)


async def test_records_every_call_with_probe_ids():
    judge = FakeJudge({})

    await judge.judge(STATE, PROBES)
    await judge.judge({"user_request": "x"}, [CATALOG["user.off_task"]])

    assert judge.calls == [
        (STATE, ("user.off_task", "drift.degree")),
        ({"user_request": "x"}, ("user.off_task",)),
    ]


async def test_callable_answers_receive_state_and_probes():
    seen: list[tuple[object, tuple[str, ...]]] = []

    def answers(state, probes):
        seen.append((state, tuple(p.id for p in probes)))
        return {p.id: 0.5 for p in probes}

    judge = FakeJudge(answers)
    result = await judge.judge(STATE, PROBES)

    assert seen == [(STATE, ("user.off_task", "drift.degree"))]
    assert [j.probability for j in result.judgments.values()] == [0.5, 0.5]


async def test_fail_when_raises_for_matching_state_only():
    judge = FakeJudge({}, fail_when=lambda state: state["user_request"] == "boom")

    with pytest.raises(RuntimeError):
        await judge.judge({"user_request": "boom"}, PROBES)

    result = await judge.judge(STATE, PROBES)
    assert set(result.judgments) == {"user.off_task", "drift.degree"}


async def test_delay_and_concurrency_tracking():
    judge = FakeJudge({}, delay_s=0.01)

    await asyncio.gather(*(judge.judge(STATE, PROBES) for _ in range(3)))

    assert judge.max_concurrent == 3
    assert judge.concurrent == 0
