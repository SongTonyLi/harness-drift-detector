"""HeuristicJudge: offline lexical rules over a window state."""

import pytest

from harness_drift_detector.adapters.heuristic_judge import HeuristicJudge
from harness_drift_detector.domain.probes import CATALOG

IGNORED_ERROR = CATALOG["tool.ignored_error"]
OFF_TASK = CATALOG["user.off_task"]
DEGREE = CATALOG["drift.degree"]


def _state(
    user_request: str = "delete the temporary files",
    previous_message: dict | None = None,
    assistant_text: str = "Done.",
    tool_calls: list[dict] | None = None,
    ends_turn: bool = True,
) -> dict:
    return {
        "user_request": user_request,
        "previous_message": previous_message or {"from": "user", "text": user_request},
        "previous_assistant_text": "",
        "assistant_step": {
            "text": assistant_text,
            "tool_calls": tool_calls or [],
            "ends_turn": ends_turn,
        },
    }


def _tools(*results: dict) -> dict:
    return {"from": "tools", "results": list(results)}


async def test_name_and_model():
    judge = HeuristicJudge()
    assert judge.name == "heuristic"
    assert judge.model == "lexical-v1"


async def test_ignored_error_fires_on_is_error_without_acknowledgement():
    state = _state(
        previous_message=_tools({"tool": "bash", "is_error": True, "text": "rm: b.py"}),
        assistant_text="Done.",
    )

    result = await HeuristicJudge().judge(state, [IGNORED_ERROR])

    assert result.judgments["tool.ignored_error"].probability == 0.9
    assert result.model == "lexical-v1"


async def test_ignored_error_fires_on_an_error_marker_in_the_text():
    state = _state(
        previous_message=_tools({"tool": "bash", "is_error": False, "text": "boom\n[exit code: 1]"}),
        assistant_text="Done.",
    )

    result = await HeuristicJudge().judge(state, [IGNORED_ERROR])

    assert result.judgments["tool.ignored_error"].probability == 0.9


async def test_ignored_error_is_low_when_the_step_acknowledges_the_failure():
    state = _state(
        previous_message=_tools({"tool": "bash", "is_error": True, "text": "Permission denied"}),
        assistant_text="That failed with a permission problem; trying another path.",
    )

    result = await HeuristicJudge().judge(state, [IGNORED_ERROR])

    assert result.judgments["tool.ignored_error"].probability == 0.1


async def test_ignored_error_is_zero_without_any_failure():
    state = _state(
        previous_message=_tools({"tool": "bash", "is_error": False, "text": "a.py\n[exit code: 0]"}),
    )

    result = await HeuristicJudge().judge(state, [IGNORED_ERROR])

    assert result.judgments["tool.ignored_error"].probability == 0.0


async def test_off_task_is_zero_when_the_step_repeats_the_request():
    state = _state(user_request="list the files", assistant_text="list the files")

    result = await HeuristicJudge().judge(state, [OFF_TASK])

    assert result.judgments["user.off_task"].probability == 0.0


async def test_off_task_uses_token_overlap_including_tool_arguments():
    state = _state(
        user_request="remove the temporary files",
        assistant_text="",
        tool_calls=[{"tool": "bash", "arguments": '{"command":"rm temporary files"}'}],
    )

    result = await HeuristicJudge().judge(state, [OFF_TASK])

    # tokens: request {remove, the, temporary, files}; step {command, temporary, files}
    assert result.judgments["user.off_task"].probability == pytest.approx(1 - 2 / 5)


async def test_off_task_is_one_half_when_the_step_has_no_content():
    state = _state(user_request="list the files", assistant_text="   ", tool_calls=[])

    result = await HeuristicJudge().judge(state, [OFF_TASK])

    assert result.judgments["user.off_task"].probability == 0.5


async def test_drift_degree_mirrors_off_task():
    state = _state(
        user_request="remove the temporary files",
        assistant_text="",
        tool_calls=[{"tool": "bash", "arguments": '{"command":"rm temporary files"}'}],
    )

    result = await HeuristicJudge().judge(state, [OFF_TASK, DEGREE])

    assert (
        result.judgments["drift.degree"].probability
        == result.judgments["user.off_task"].probability
    )


async def test_other_probes_are_undecided():
    probes = [CATALOG["adjacent.ignores_previous"], CATALOG["goal.premature_stop"]]

    result = await HeuristicJudge().judge(_state(), probes)

    assert set(result.judgments) == {"adjacent.ignores_previous", "goal.premature_stop"}
    for judgment in result.judgments.values():
        assert judgment.probability == 0.5
        assert judgment.confidence == 0.0
