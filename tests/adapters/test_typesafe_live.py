"""One real TypeSafe call. Skipped unless TYPESAFE_API_KEY is set in the environment."""

import os

import pytest

from harness_drift_detector.adapters.typesafe_judge import TypeSafeJudge
from harness_drift_detector.domain.probes import CATALOG

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("TYPESAFE_API_KEY"), reason="TYPESAFE_API_KEY is not set"),
]

STATE = {
    "user_request": "list the files in this directory",
    "previous_message": {"from": "user", "text": "list the files in this directory"},
    "previous_assistant_text": "",
    "assistant_step": {
        "text": "Here is a haiku about autumn leaves.",
        "tool_calls": [],
        "ends_turn": True,
    },
}


async def test_live_system_one_call():
    judge = TypeSafeJudge()
    try:
        result = await judge.judge(STATE, [CATALOG["user.off_task"], CATALOG["drift.degree"]])
    finally:
        await judge.aclose()

    assert result.model.startswith("jev")
    assert set(result.judgments) == {"user.off_task", "drift.degree"}
    for judgment in result.judgments.values():
        assert 0.0 <= judgment.probability <= 1.0
    assert result.latency_s > 0
