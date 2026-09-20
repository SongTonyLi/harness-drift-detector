from harness_drift_detector.domain.judgment import JudgeResult, Judgment, Usage
from harness_drift_detector.domain.policy import (
    EXCERPT_CHARS,
    DriftPolicy,
    FiredProbe,
    Hotspot,
    gate,
    rank,
)
from harness_drift_detector.domain.window import PreviousMessage, StepCall, Window


def _window(**kwargs):
    base = dict(
        transcript_id="s1",
        turn=1,
        step=1,
        seq=5,
        user_request="list the files",
        previous_message=PreviousMessage(source="user", text="list the files"),
        previous_assistant_text="",
        assistant_text="Let me tell you about something else entirely. " * 10,
        tool_calls=(),
        ends_turn=False,
    )
    base.update(kwargs)
    return Window(**base)


def _result(probabilities, model="jev-1.13.0"):
    return JudgeResult(
        judgments={
            pid: Judgment(pid, prob) for pid, prob in probabilities.items()
        },
        model=model,
        usage=Usage(10, 2),
    )


PROBS = {"user.off_task": 0.9, "adjacent.ignores_previous": 0.2, "drift.degree": 0.66}


def test_gate_fires_on_noul_above_threshold():
    window = _window()
    hotspot = gate(window, _result(PROBS), DriftPolicy())
    assert hotspot is not None
    assert hotspot.fired == (FiredProbe("user.off_task", 0.9, 0.7),)
    assert hotspot.severity == 0.9
    assert hotspot.drift_degree == 0.66
    assert hotspot.excerpt == window.assistant_text[:EXCERPT_CHARS]
    assert hotspot.window_id == "s1:t1:s1"
    assert hotspot.turn == 1 and hotspot.step == 1 and hotspot.seq == 5
    assert hotspot.judgments == _result(PROBS).judgments


def test_score_probe_alone_never_fires():
    probs = {"user.off_task": 0.1, "adjacent.ignores_previous": 0.2, "drift.degree": 1.0}
    assert gate(_window(), _result(probs), DriftPolicy()) is None


def test_threshold_is_strict():
    assert gate(_window(), _result({"user.off_task": 0.7}), DriftPolicy()) is None
    assert gate(_window(), _result({"user.off_task": 0.71}), DriftPolicy()) is not None


def test_override_lowers_threshold():
    policy = DriftPolicy(overrides={"adjacent.ignores_previous": 0.1})
    hotspot = gate(_window(), _result(PROBS), policy)
    assert hotspot is not None
    assert [f.probe_id for f in hotspot.fired] == ["user.off_task", "adjacent.ignores_previous"]
    assert hotspot.fired[1] == FiredProbe("adjacent.ignores_previous", 0.2, 0.1)
    assert hotspot.severity == 0.9


def test_excerpt_falls_back_to_first_tool_call():
    window = _window(assistant_text="", tool_calls=(StepCall("bash", '{"command":"ls"}'),))
    hotspot = gate(window, _result(PROBS), DriftPolicy())
    assert hotspot is not None
    assert hotspot.excerpt == 'bash {"command":"ls"}'


def test_excerpt_is_empty_without_text_or_calls():
    hotspot = gate(_window(assistant_text=""), _result(PROBS), DriftPolicy())
    assert hotspot is not None
    assert hotspot.excerpt == ""


def test_unknown_probe_ids_do_not_fire():
    assert gate(_window(), _result({"not.a.probe": 1.0}), DriftPolicy()) is None


def test_missing_drift_degree_leaves_none():
    hotspot = gate(_window(), _result({"user.off_task": 0.9}), DriftPolicy())
    assert hotspot is not None and hotspot.drift_degree is None


def _hotspot(severity, drift_degree, turn=1, step=1, transcript_id="s1"):
    return Hotspot(
        transcript_id=transcript_id,
        turn=turn,
        step=step,
        seq=turn * 100 + step,
        fired=(FiredProbe("user.off_task", severity, 0.7),),
        severity=severity,
        drift_degree=drift_degree,
        excerpt="",
        judgments={},
    )


def test_rank_orders_by_severity_then_drift_degree_then_position():
    a = _hotspot(0.8, 0.3)
    b = _hotspot(0.9, None)
    c = _hotspot(0.9, 0.5)
    d = _hotspot(0.8, 0.3, turn=1, step=2)
    assert rank([a, b, c, d]) == [c, b, a, d]


def test_rank_does_not_mutate_input():
    a = _hotspot(0.8, 0.3)
    b = _hotspot(0.9, 0.5)
    original = [a, b]
    assert rank(original) == [b, a]
    assert original == [a, b]
    assert rank([]) == []
