from harness_drift_detector.domain.judgment import JudgeResult, Judgment, Usage
from harness_drift_detector.domain.policy import DriftPolicy
from harness_drift_detector.domain.probes import CATALOG
from harness_drift_detector.domain.report import WindowOutcome, build_report
from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
)
from harness_drift_detector.domain.window import build_windows


def _transcript():
    return Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "list the files", "human"),
            AssistantEvent(2, 1, 1, "I'll list them.", (ToolCall("c1", "bash", "{}"),), "toolUse"),
            ToolResultEvent(3, 1, 1, "c1", "bash", "a.py", False),
            AssistantEvent(4, 1, 2, "There is one file.", (), "stop"),
            TurnEndEvent(5, 1, "completed"),
            UserEvent(6, 2, "delete it", "human"),
            AssistantEvent(7, 2, 1, "Anyway, here is a poem.", (), "stop"),
            TurnEndEvent(8, 2, "completed"),
        ),
    )


def _result(probabilities, usage=Usage(10, 2)):
    return JudgeResult(
        judgments={pid: Judgment(pid, p) for pid, p in probabilities.items()},
        model="jev-1.13.0",
        usage=usage,
    )


def _outcomes():
    w1, w2, w3 = build_windows(_transcript())
    return [
        WindowOutcome(w1, _result({"user.off_task": 0.1, "drift.degree": 0.0})),
        WindowOutcome(
            w2,
            _result(
                {"user.off_task": 0.9, "adjacent.ignores_previous": 0.3, "drift.degree": 1.0},
                usage=Usage(20, 5),
            ),
        ),
        WindowOutcome(w3, None, error="boom"),
    ]


def _report(policy=DriftPolicy()):
    return build_report(_transcript(), _outcomes(), policy, "fake", "jev-1.13.0", 1.25)


def test_report_counts():
    report = _report()
    assert report.transcript_id == "s1"
    assert report.judge_name == "fake" and report.judge_model == "jev-1.13.0"
    assert report.turns == 2
    assert report.steps == 3
    assert report.windows_judged == 2
    assert report.windows_failed == 1
    assert report.probes_asked == 5
    assert report.wall_time_s == 1.25
    assert report.usage == Usage(30, 7)
    assert report.outcomes == tuple(_outcomes())
    assert report.policy == DriftPolicy()


def test_probe_stats():
    stats = {s.probe_id: s for s in _report().probe_stats}
    assert set(stats) == {"user.off_task", "adjacent.ignores_previous", "drift.degree"}
    off_task = stats["user.off_task"]
    assert off_task.count == 2
    assert off_task.mean == 0.5
    assert off_task.max == 0.9
    assert off_task.fired == 1
    assert stats["adjacent.ignores_previous"].count == 1
    assert stats["adjacent.ignores_previous"].fired == 0
    assert stats["drift.degree"].max == 1.0
    assert stats["drift.degree"].fired == 0  # score probes never fire


def test_probe_stats_follow_catalog_order():
    order = [s.probe_id for s in _report().probe_stats]
    assert order == [pid for pid in CATALOG if pid in set(order)]


def test_hotspots_are_gated_and_ranked():
    report = _report()
    assert [h.window_id for h in report.hotspots] == ["s1:t1:s2"]
    assert report.hotspots[0].severity == 0.9
    assert report.hotspots[0].drift_degree == 1.0


def test_policy_changes_hotspots_and_fired_counts():
    report = _report(DriftPolicy(fire_threshold=0.2))
    assert [h.window_id for h in report.hotspots] == ["s1:t1:s2"]
    stats = {s.probe_id: s for s in report.probe_stats}
    assert stats["adjacent.ignores_previous"].fired == 1
    assert stats["drift.degree"].fired == 0
    assert report.policy == DriftPolicy(fire_threshold=0.2)


def test_empty_outcomes():
    report = build_report(_transcript(), [], DriftPolicy(), "fake", "none", 0.0)
    assert report.windows_judged == 0
    assert report.windows_failed == 0
    assert report.probes_asked == 0
    assert report.probe_stats == ()
    assert report.hotspots == ()
    assert report.usage == Usage(0, 0)
