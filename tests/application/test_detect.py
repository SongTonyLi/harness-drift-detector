"""DetectDrift: one judge call per window, bounded concurrency, failures recorded."""

from __future__ import annotations

from harness_drift_detector.adapters.fake_judge import FakeJudge
from harness_drift_detector.application.detect import DetectDrift, DetectOptions
from harness_drift_detector.domain.judgment import Usage
from harness_drift_detector.domain.policy import DriftPolicy
from harness_drift_detector.domain.probes import select_probes
from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    SystemEvent,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
)
from harness_drift_detector.domain.window import build_windows

USAGE = Usage(3, 1)


def _judge(answers=None, **kwargs) -> FakeJudge:
    return FakeJudge(answers or {}, usage=USAGE, **kwargs)


def _transcript(transcript_id: str = "s1") -> Transcript:
    return Transcript(
        TranscriptHeader(transcript_id, "dsh", "/p"),
        (
            SystemEvent(1, 1, 1, "system prompt"),
            UserEvent(2, 1, "runtime snapshot", "harness"),
            UserEvent(3, 1, "list the files", "human"),
            AssistantEvent(
                5, 1, 1, "I'll list them.", (ToolCall("c1", "bash", '{"command":"ls"}'),), "toolUse"
            ),
            ToolResultEvent(6, 1, 1, "c1", "bash", "a.py\nb.py", False),
            AssistantEvent(7, 1, 2, "There are two files.", (), "stop"),
            TurnEndEvent(8, 1, "completed"),
            UserEvent(9, 2, "delete b.py", "human"),
            AssistantEvent(
                10, 2, 1, "", (ToolCall("c2", "bash", '{"command":"rm b.py"}'),), "toolUse"
            ),
            ToolResultEvent(
                11, 2, 1, "c2", "bash", "rm: b.py: Permission denied\n[exit code: 1]", True
            ),
            AssistantEvent(12, 2, 2, "Done.", (), "stop"),
            TurnEndEvent(13, 2, "completed"),
        ),
    )


async def test_one_judge_call_per_window_with_selected_probes():
    transcript = _transcript()
    judge = _judge()
    report = await DetectDrift(judge).run(transcript)

    windows = build_windows(transcript)
    expected = [tuple(p.id for p in select_probes(w)) for w in windows]
    assert [probe_ids for _state, probe_ids in judge.calls] == expected
    assert [state["assistant_step"]["text"] for state, _ in judge.calls] == [
        "I'll list them.",
        "There are two files.",
        "",
        "Done.",
    ]
    assert report.transcript_id == "s1"
    assert report.judge_name == "fake" and report.judge_model == "fake"
    assert report.windows_judged == 4 and report.windows_failed == 0
    assert report.probes_asked == sum(len(ids) for ids in expected)
    assert report.usage == Usage(12, 4)
    assert report.wall_time_s >= 0.0


async def test_failing_window_is_recorded_not_raised():
    judge = _judge(fail_when=lambda state: state["assistant_step"]["text"] == "Done.")
    report = await DetectDrift(judge).run(_transcript())

    assert report.windows_judged == 3 and report.windows_failed == 1
    failed = [o for o in report.outcomes if o.error is not None]
    assert len(failed) == 1
    assert "FakeJudge failure" in failed[0].error
    assert failed[0].result is None
    assert failed[0].window.window_id == "s1:t2:s2"


async def test_concurrency_is_bounded_by_the_semaphore():
    judge = _judge(delay_s=0.01)
    await DetectDrift(judge, DetectOptions(concurrency=2)).run(_transcript())
    assert judge.max_concurrent == 2

    wide = _judge(delay_s=0.01)
    await DetectDrift(wide, DetectOptions(concurrency=8)).run(_transcript())
    assert wide.max_concurrent == 4


async def test_only_probes_restricts_the_batch_and_skips_empty_windows():
    judge = _judge()
    report = await DetectDrift(judge, DetectOptions(only_probes={"user.off_task"})).run(
        _transcript()
    )
    assert [probe_ids for _state, probe_ids in judge.calls] == [("user.off_task",)] * 4

    narrow = _judge()
    await DetectDrift(narrow, DetectOptions(only_probes={"tool.ignored_error"})).run(_transcript())
    assert [probe_ids for _state, probe_ids in narrow.calls] == [("tool.ignored_error",)]
    assert report.windows_judged == 4


async def test_hotspots_come_from_the_policy():
    judge = _judge({"user.off_task": 0.9, "drift.degree": 0.66})
    report = await DetectDrift(judge, DetectOptions(policy=DriftPolicy(fire_threshold=0.7))).run(
        _transcript()
    )
    assert len(report.hotspots) == 4
    assert report.hotspots[0].severity == 0.9
    assert report.hotspots[0].fired[0].probe_id == "user.off_task"

    calm = _judge({"user.off_task": 0.5})
    quiet = await DetectDrift(calm, DetectOptions(policy=DriftPolicy(fire_threshold=0.7))).run(
        _transcript()
    )
    assert quiet.hotspots == ()


async def test_run_many_shares_one_semaphore():
    judge = _judge(delay_s=0.01)
    reports = await DetectDrift(judge, DetectOptions(concurrency=3)).run_many(
        [_transcript("s1"), _transcript("s2")]
    )
    assert [r.transcript_id for r in reports] == ["s1", "s2"]
    assert judge.max_concurrent == 3
    assert len(judge.calls) == 8
