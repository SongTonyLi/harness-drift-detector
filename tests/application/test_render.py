"""Renderers: JSON (full report), Markdown (tables), terminal (compact)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from harness_drift_detector.application.render import (
    render_hotspots,
    render_json,
    render_markdown,
    render_terminal,
    report_to_dict,
)
from harness_drift_detector.domain.judgment import JudgeResult, Judgment, Usage
from harness_drift_detector.domain.policy import DriftPolicy, FiredProbe, Hotspot
from harness_drift_detector.domain.report import DriftReport, ProbeStats, WindowOutcome
from harness_drift_detector.domain.window import PreviousMessage, ToolOutcome, Window

JUDGMENTS = {
    "user.off_task": Judgment("user.off_task", 0.9, raw={"noul": 0.9}),
    "adjacent.ignores_previous": Judgment("adjacent.ignores_previous", 0.2),
    "drift.degree": Judgment("drift.degree", 0.6666666, confidence=0.42),
}


@dataclass(frozen=True)
class StubWindow:
    """Duck-typed stand-in: report_to_dict only needs ids and to_state()."""

    window_id: str
    turn: int
    step: int
    seq: int
    state: dict[str, Any]

    def to_state(self) -> dict[str, Any]:
        return self.state


def _hotspot(step: int = 2, severity: float = 0.9, excerpt: str = "There are two files.") -> Hotspot:
    return Hotspot(
        transcript_id="s1",
        turn=1,
        step=step,
        seq=6 + step,
        fired=(FiredProbe("user.off_task", severity, 0.7),),
        severity=severity,
        drift_degree=0.6666666,
        excerpt=excerpt,
        judgments=JUDGMENTS,
    )


def _report(hotspots=None, outcomes=()) -> DriftReport:
    return DriftReport(
        transcript_id="s1",
        judge_name="typesafe",
        judge_model="jev-1.13.0",
        turns=2,
        steps=4,
        windows_judged=3,
        windows_failed=1,
        probes_asked=9,
        wall_time_s=1.25,
        usage=Usage(1200, 34),
        probe_stats=(
            ProbeStats("user.off_task", 3, 0.5, 0.9, 1),
            ProbeStats("drift.degree", 3, 0.44, 0.67, 0),
        ),
        hotspots=(_hotspot(),) if hotspots is None else tuple(hotspots),
        outcomes=tuple(outcomes),
        policy=DriftPolicy(fire_threshold=0.7, overrides={"tool.ignored_error": 0.5}),
    )


def test_report_to_dict_is_json_safe_and_complete():
    data = report_to_dict(_report(hotspots=(_hotspot(),)))
    assert data["transcript_id"] == "s1"
    assert data["judge_name"] == "typesafe" and data["judge_model"] == "jev-1.13.0"
    assert data["turns"] == 2 and data["steps"] == 4
    assert data["windows_judged"] == 3 and data["windows_failed"] == 1
    assert data["probes_asked"] == 9
    assert data["usage"] == {"input_tokens": 1200, "output_tokens": 34}
    assert data["policy"] == {"fire_threshold": 0.7, "overrides": {"tool.ignored_error": 0.5}}
    assert data["probe_stats"][0] == {
        "probe_id": "user.off_task",
        "count": 3,
        "mean": 0.5,
        "max": 0.9,
        "fired": 1,
    }
    hotspot = data["hotspots"][0]
    assert hotspot["rank"] == 1
    assert hotspot["window_id"] == "s1:t1:s2"
    assert hotspot["turn"] == 1 and hotspot["step"] == 2 and hotspot["seq"] == 8
    assert hotspot["severity"] == 0.9
    assert hotspot["fired"] == [{"probe_id": "user.off_task", "probability": 0.9, "threshold": 0.7}]
    assert hotspot["judgments"]["drift.degree"] == {"probability": 0.6666666, "confidence": 0.42}
    assert hotspot["judgments"]["user.off_task"] == {"probability": 0.9, "confidence": None}
    assert data["windows"] == []
    json.dumps(data)  # no non-serializable leftovers


def test_report_to_dict_serializes_window_outcomes():
    state = {
        "user_request": "list the files",
        "previous_message": {"from": "user", "text": "list the files"},
        "previous_assistant_text": "",
        "assistant_step": {"text": "ok", "tool_calls": [], "ends_turn": True},
    }
    judged = WindowOutcome(
        window=StubWindow("s1:t1:s1", 1, 1, 5, state),
        result=JudgeResult(judgments=JUDGMENTS, model="jev-1.13.0", usage=Usage(10, 2), latency_s=0.3),
    )
    failed = WindowOutcome(window=StubWindow("s1:t1:s2", 1, 2, 7, state), result=None, error="RuntimeError('boom')")
    data = report_to_dict(_report(outcomes=(judged, failed)))

    first, second = data["windows"]
    assert first["window_id"] == "s1:t1:s1" and first["state"] == state
    assert first["error"] is None and first["cached"] is False
    assert first["latency_s"] == 0.3
    assert first["judgments"]["user.off_task"] == {"probability": 0.9, "confidence": None}
    assert second["error"] == "RuntimeError('boom')" and second["judgments"] == {}
    json.dumps(data)


def test_render_json_round_trips():
    report = _report()
    assert json.loads(render_json(report)) == report_to_dict(report)


def test_render_markdown_has_the_three_tables():
    text = render_markdown(_report())
    assert text.startswith("# Drift report: s1")
    assert "typesafe" in text and "jev-1.13.0" in text
    assert "## Summary" in text and "## Probes" in text and "## Hotspots" in text
    assert "| turns | 2 |" in text
    assert "| windows judged | 3 |" in text
    assert "| windows failed | 1 |" in text
    assert "| probes asked | 9 |" in text
    assert "| input tokens | 1200 |" in text
    assert "| user.off_task | 3 | 0.500 | 0.900 | 1 |" in text
    assert "| 1 | s1:t1:s2 | 0.90 | user.off_task=0.90 | 0.67 | There are two files. |" in text


def test_render_markdown_without_hotspots():
    text = render_markdown(_report(hotspots=()))
    assert "No hotspots above threshold 0.70" in text


def test_render_markdown_escapes_table_breaking_characters():
    text = render_markdown(_report(hotspots=(_hotspot(excerpt="a | b\nc"),)))
    row = [line for line in text.splitlines() if line.startswith("| 1 |")][0]
    assert "a \\| b c" in row


def test_render_terminal_is_one_line_per_hotspot_plus_a_summary():
    text = render_terminal(_report(hotspots=(_hotspot(), _hotspot(step=3, severity=0.75))))
    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("s1")
    assert "judged=3" in lines[0] and "failed=1" in lines[0] and "hotspots=2" in lines[0]
    assert "1. s1:t1:s2" in lines[1] and "0.90" in lines[1] and "user.off_task" in lines[1]
    assert "2. s1:t1:s3" in lines[2]


def test_render_terminal_without_hotspots():
    text = render_terminal(_report(hotspots=()))
    assert text.splitlines() == [text.strip()]
    assert "hotspots=0" in text


def test_render_hotspots_reads_a_saved_report_dict_and_honours_top():
    data = json.loads(render_json(_report(hotspots=(_hotspot(), _hotspot(step=3, severity=0.75)))))
    both = render_hotspots(data)
    assert "s1:t1:s2" in both and "s1:t1:s3" in both

    only_first = render_hotspots(data, top=1)
    assert "s1:t1:s2" in only_first and "s1:t1:s3" not in only_first


def test_report_to_dict_uses_the_real_window_state():
    window = Window(
        transcript_id="s1",
        turn=1,
        step=2,
        seq=7,
        user_request="list the files",
        previous_message=PreviousMessage(source="tools", results=(ToolOutcome("bash", False, "a.py"),)),
        previous_assistant_text="I'll list them.",
        assistant_text="There are two files.",
        tool_calls=(),
        ends_turn=True,
    )
    outcome = WindowOutcome(window=window, result=JudgeResult(judgments=JUDGMENTS, model="jev-1.13.0"))
    data = report_to_dict(_report(outcomes=(outcome,)))
    assert data["windows"][0]["state"]["previous_message"] == {
        "from": "tools",
        "results": [{"tool": "bash", "is_error": False, "text": "a.py"}],
    }


def test_render_hotspots_reports_the_total_even_when_top_shows_none():
    data = json.loads(render_json(_report(hotspots=(_hotspot(), _hotspot(step=3, severity=0.75)))))

    assert "no hotspots" not in render_hotspots(data, top=0)
    assert "2 hotspot(s)" in render_hotspots(data, top=0)
    assert "1 of 2 hotspot(s)" in render_hotspots(data, top=1)
    assert "2 hotspot(s)" in render_hotspots(data)


def test_render_hotspots_says_none_only_for_a_report_without_hotspots():
    data = json.loads(render_json(_report(hotspots=())))

    assert "no hotspots" in render_hotspots(data)
