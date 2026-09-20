"""`hdd` command line: convert, detect, hotspots."""

from __future__ import annotations

import json

import pytest

from harness_drift_detector.application.render import render_json
from harness_drift_detector.cli import main
from harness_drift_detector.domain.judgment import Judgment, Usage
from harness_drift_detector.domain.policy import DriftPolicy, FiredProbe, Hotspot
from harness_drift_detector.domain.report import DriftReport, ProbeStats


def _hotspot(step: int, severity: float) -> Hotspot:
    judgments = {"user.off_task": Judgment("user.off_task", severity)}
    return Hotspot(
        transcript_id="s1",
        turn=1,
        step=step,
        seq=4 + step,
        fired=(FiredProbe("user.off_task", severity, 0.7),),
        severity=severity,
        drift_degree=0.5,
        excerpt=f"step {step} text",
        judgments=judgments,
    )


def _report_file(tmp_path, hotspots):
    report = DriftReport(
        transcript_id="s1",
        judge_name="heuristic",
        judge_model="lexical-v1",
        turns=1,
        steps=2,
        windows_judged=2,
        windows_failed=0,
        probes_asked=6,
        wall_time_s=0.1,
        usage=Usage(),
        probe_stats=(ProbeStats("user.off_task", 2, 0.8, 0.9, 2),),
        hotspots=tuple(hotspots),
        policy=DriftPolicy(),
    )
    path = tmp_path / "s1.json"
    path.write_text(render_json(report), encoding="utf-8")
    return path


def test_no_command_exits_with_usage():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_detect_with_typesafe_and_no_key_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    code = main(
        ["detect", str(tmp_path / "nope.jsonl"), "--judge", "typesafe", "--out", str(tmp_path)]
    )
    assert code == 2
    assert "TYPESAFE_API_KEY is not set" in capsys.readouterr().err


def test_hotspots_prints_ranked_windows(tmp_path, capsys):
    path = _report_file(tmp_path, [_hotspot(1, 0.9), _hotspot(2, 0.75)])
    assert main(["hotspots", str(path)]) == 0
    out = capsys.readouterr().out
    assert "s1:t1:s1" in out and "s1:t1:s2" in out
    assert "0.90" in out


def test_hotspots_top_limits_the_output(tmp_path, capsys):
    path = _report_file(tmp_path, [_hotspot(1, 0.9), _hotspot(2, 0.75)])
    assert main(["hotspots", str(path), "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "s1:t1:s1" in out and "s1:t1:s2" not in out


def test_hotspots_without_hotspots(tmp_path, capsys):
    path = _report_file(tmp_path, [])
    assert main(["hotspots", str(path)]) == 0
    assert "no hotspots" in capsys.readouterr().out


def test_hotspots_missing_file_exits_2(tmp_path, capsys):
    assert main(["hotspots", str(tmp_path / "missing.json")]) == 2
    assert "missing.json" in capsys.readouterr().err


def test_detect_with_no_readable_transcripts_warns_and_exits_1(tmp_path, capsys):
    code = main(
        ["detect", str(tmp_path / "nope.jsonl"), "--judge", "heuristic", "--out", str(tmp_path)]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "nope.jsonl" in captured.err


@pytest.mark.integration
def test_convert_then_detect_writes_reports(tmp_path, capsys):
    from tests.fixtures.dsh_v3 import write_session_dir

    root = tmp_path / "sessions"
    write_session_dir(root, "session-fixture", compressed=False)
    out = tmp_path / "transcripts"

    assert main(["convert", "--harness", "dsh", "--root", str(root), "--out", str(out)]) == 0
    written = sorted(out.glob("*.jsonl"))
    assert [p.name for p in written] == ["session-fixture.jsonl"]

    reports = tmp_path / "reports"
    code = main(
        [
            "detect",
            str(written[0]),
            "--judge",
            "heuristic",
            "--out",
            str(reports),
            "--no-cache",
        ]
    )
    assert code == 0
    assert (reports / "session-fixture.json").exists()
    assert (reports / "session-fixture.md").exists()
    data = json.loads((reports / "session-fixture.json").read_text(encoding="utf-8"))
    assert data["transcript_id"] == "session-fixture"
    assert data["windows_judged"] >= 1
    assert "session-fixture" in capsys.readouterr().out


@pytest.mark.integration
def test_detect_caches_between_runs(tmp_path):
    from tests.fixtures.dsh_v3 import write_session_dir

    root = tmp_path / "sessions"
    write_session_dir(root, "session-fixture", compressed=False)
    out = tmp_path / "transcripts"
    main(["convert", "--harness", "dsh", "--root", str(root), "--out", str(out)])
    transcript = str(sorted(out.glob("*.jsonl"))[0])
    cache = tmp_path / "cache"

    args = [
        "detect",
        transcript,
        "--judge",
        "heuristic",
        "--out",
        str(tmp_path / "reports"),
        "--cache-dir",
        str(cache),
    ]
    assert main(args) == 0
    keys = sorted(cache.glob("*.json"))
    assert keys
    assert main(args) == 0
    assert sorted(cache.glob("*.json")) == keys


def test_hotspots_on_json_that_is_not_a_report_exits_2(tmp_path, capsys):
    path = tmp_path / "other.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    assert main(["hotspots", str(path)]) == 2
    assert "not a drift report" in capsys.readouterr().err


def _transcript_file(tmp_path):
    path = tmp_path / "s1.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"kind":"transcript","transcript_id":"s1","harness":"dsh","source_path":"/p"}',
                '{"kind":"user","seq":1,"turn":1,"text":"list the files","origin":"human"}',
                '{"kind":"assistant","seq":2,"turn":1,"step":1,"text":"a.py and b.py",'
                '"tool_calls":[],"stop_reason":"stop"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_detect_requires_an_explicit_judge(tmp_path):
    """The offline lexical judge is a baseline, not a default: the choice is the user's."""
    with pytest.raises(SystemExit) as exc:
        main(["detect", str(_transcript_file(tmp_path)), "--out", str(tmp_path / "reports")])
    assert exc.value.code == 2


def test_detect_with_an_unknown_probe_id_exits_2(tmp_path, capsys):
    code = main(
        [
            "detect",
            str(_transcript_file(tmp_path)),
            "--judge",
            "heuristic",
            "--out",
            str(tmp_path / "reports"),
            "--no-cache",
            "--probes",
            "user.offtask",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "user.offtask" in err and "user.off_task" in err
    assert not (tmp_path / "reports").exists()


def test_detect_accepts_known_probe_ids(tmp_path):
    code = main(
        [
            "detect",
            str(_transcript_file(tmp_path)),
            "--judge",
            "heuristic",
            "--out",
            str(tmp_path / "reports"),
            "--no-cache",
            "--probes",
            "user.off_task",
        ]
    )
    assert code == 0
    data = json.loads((tmp_path / "reports" / "s1.json").read_text(encoding="utf-8"))
    assert data["windows_judged"] == 1


@pytest.mark.parametrize("value", ["0", "-1"])
def test_detect_rejects_a_non_positive_concurrency(tmp_path, value):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "detect",
                str(_transcript_file(tmp_path)),
                "--judge",
                "heuristic",
                "--out",
                str(tmp_path / "reports"),
                "--no-cache",
                "--concurrency",
                value,
            ]
        )
    assert exc.value.code == 2


def test_hotspots_rejects_a_non_positive_top(tmp_path):
    path = _report_file(tmp_path, [_hotspot(1, 0.9)])
    with pytest.raises(SystemExit) as exc:
        main(["hotspots", str(path), "--top", "0"])
    assert exc.value.code == 2


def test_convert_rejects_ids_without_values(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["convert", "--root", str(tmp_path), "--out", str(tmp_path / "out"), "--ids"])
    assert exc.value.code == 2


def test_detect_override_raises_one_probe_threshold(tmp_path):
    reports = tmp_path / "reports"
    code = main(
        [
            "detect",
            str(_transcript_file(tmp_path)),
            "--judge",
            "heuristic",
            "--out",
            str(reports),
            "--no-cache",
            "--override",
            "tool.unsupported_claim=0.95",
            "--override",
            "user.off_task=1.0",
        ]
    )
    assert code == 0
    data = json.loads(next(reports.glob("*.json")).read_text(encoding="utf-8"))
    assert data["policy"]["overrides"] == {"tool.unsupported_claim": 0.95, "user.off_task": 1.0}
    assert not any(
        fired["probe_id"] == "user.off_task" for h in data["hotspots"] for fired in h["fired"]
    )


@pytest.mark.parametrize(
    "value", ["user.offtask=0.9", "user.off_task", "user.off_task=x", "user.off_task=1.5"]
)
def test_detect_rejects_a_bad_override(tmp_path, capsys, value):
    code = main(
        [
            "detect",
            str(_transcript_file(tmp_path)),
            "--judge",
            "heuristic",
            "--out",
            str(tmp_path / "reports"),
            "--no-cache",
            "--override",
            value,
        ]
    )
    assert code == 2
    assert "bad --override" in capsys.readouterr().err
