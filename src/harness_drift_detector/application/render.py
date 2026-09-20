"""Renderers: a DriftReport becomes JSON, Markdown, or a compact terminal summary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..domain.judgment import Judgment
from ..domain.report import DriftReport

TERMINAL_EXCERPT_CHARS = 120


def _judgments_to_dict(judgments: Mapping[str, Judgment]) -> dict[str, dict[str, Any]]:
    return {
        probe_id: {"probability": j.probability, "confidence": j.confidence}
        for probe_id, j in judgments.items()
    }


def report_to_dict(report: DriftReport) -> dict[str, Any]:
    """JSON-safe view of the whole report: counts, stats, hotspots, and every window."""
    windows = []
    for outcome in report.outcomes:
        result = outcome.result
        windows.append(
            {
                "window_id": outcome.window.window_id,
                "turn": outcome.window.turn,
                "step": outcome.window.step,
                "seq": outcome.window.seq,
                "state": outcome.window.to_state(),
                "error": outcome.error,
                "model": result.model if result else None,
                "usage": {
                    "input_tokens": result.usage.input_tokens if result else 0,
                    "output_tokens": result.usage.output_tokens if result else 0,
                },
                "latency_s": result.latency_s if result else 0.0,
                "cached": result.cached if result else False,
                "judgments": _judgments_to_dict(result.judgments) if result else {},
            }
        )

    hotspots = []
    for rank, hotspot in enumerate(report.hotspots, start=1):
        hotspots.append(
            {
                "rank": rank,
                "window_id": hotspot.window_id,
                "turn": hotspot.turn,
                "step": hotspot.step,
                "seq": hotspot.seq,
                "severity": hotspot.severity,
                "drift_degree": hotspot.drift_degree,
                "excerpt": hotspot.excerpt,
                "fired": [
                    {"probe_id": f.probe_id, "probability": f.probability, "threshold": f.threshold}
                    for f in hotspot.fired
                ],
                "judgments": _judgments_to_dict(hotspot.judgments),
            }
        )

    return {
        "transcript_id": report.transcript_id,
        "judge_name": report.judge_name,
        "judge_model": report.judge_model,
        "turns": report.turns,
        "steps": report.steps,
        "windows_judged": report.windows_judged,
        "windows_failed": report.windows_failed,
        "probes_asked": report.probes_asked,
        "wall_time_s": report.wall_time_s,
        "usage": {
            "input_tokens": report.usage.input_tokens,
            "output_tokens": report.usage.output_tokens,
        },
        "policy": {
            "fire_threshold": report.policy.fire_threshold,
            "overrides": dict(report.policy.overrides),
        },
        "probe_stats": [
            {
                "probe_id": s.probe_id,
                "count": s.count,
                "mean": s.mean,
                "max": s.max,
                "fired": s.fired,
            }
            for s in report.probe_stats
        ],
        "hotspots": hotspots,
        "windows": windows,
    }


def render_json(report: DriftReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, ensure_ascii=False)


def _flatten(text: str, limit: int | None = None) -> str:
    flat = " ".join(text.split())
    if limit is not None and len(flat) > limit:
        flat = flat[: limit - 1].rstrip() + "…"
    return flat


def _cell(text: str) -> str:
    return _flatten(text).replace("|", "\\|")


def _fired_summary(hotspot: Mapping[str, Any]) -> str:
    return ", ".join(f"{f['probe_id']}={f['probability']:.2f}" for f in hotspot["fired"])


def _degree(hotspot: Mapping[str, Any]) -> str:
    degree = hotspot["drift_degree"]
    return "-" if degree is None else f"{degree:.2f}"


def render_markdown(report: DriftReport) -> str:
    data = report_to_dict(report)
    lines = [
        f"# Drift report: {data['transcript_id']}",
        "",
        f"Judge: {data['judge_name']} ({data['judge_model']})",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| turns | {data['turns']} |",
        f"| steps | {data['steps']} |",
        f"| windows judged | {data['windows_judged']} |",
        f"| windows failed | {data['windows_failed']} |",
        f"| probes asked | {data['probes_asked']} |",
        f"| wall time | {data['wall_time_s']:.2f}s |",
        f"| input tokens | {data['usage']['input_tokens']} |",
        f"| output tokens | {data['usage']['output_tokens']} |",
        "",
        "## Probes",
        "",
        "| probe | count | mean | max | fired |",
        "| --- | --- | --- | --- | --- |",
    ]
    for stat in data["probe_stats"]:
        lines.append(
            f"| {stat['probe_id']} | {stat['count']} | {stat['mean']:.3f} | "
            f"{stat['max']:.3f} | {stat['fired']} |"
        )
    if not data["probe_stats"]:
        lines.append("| (none) | 0 | 0.000 | 0.000 | 0 |")

    lines += ["", "## Hotspots", ""]
    if not data["hotspots"]:
        lines.append(f"No hotspots above threshold {data['policy']['fire_threshold']:.2f}.")
    else:
        lines += [
            "| rank | window | severity | fired | drift degree | excerpt |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for hotspot in data["hotspots"]:
            lines.append(
                f"| {hotspot['rank']} | {hotspot['window_id']} | {hotspot['severity']:.2f} | "
                f"{_cell(_fired_summary(hotspot))} | {_degree(hotspot)} | "
                f"{_cell(hotspot['excerpt'])} |"
            )
    return "\n".join(lines) + "\n"


def _hotspot_lines(data: Mapping[str, Any], top: int | None = None) -> list[str]:
    hotspots = list(data["hotspots"])
    if top is not None:
        hotspots = hotspots[:top]
    return [
        f"  {h['rank']}. {h['window_id']}  sev={h['severity']:.2f}  {_fired_summary(h)}  "
        f"degree={_degree(h)}  {_flatten(h['excerpt'], TERMINAL_EXCERPT_CHARS)}".rstrip()
        for h in hotspots
    ]


def render_terminal(report: DriftReport) -> str:
    """One summary line plus one line per hotspot."""
    data = report_to_dict(report)
    summary = (
        f"{data['transcript_id']}  judge={data['judge_name']}/{data['judge_model']}  "
        f"turns={data['turns']} steps={data['steps']} judged={data['windows_judged']} "
        f"failed={data['windows_failed']} probes={data['probes_asked']} "
        f"hotspots={len(data['hotspots'])}  {data['wall_time_s']:.2f}s"
    )
    return "\n".join([summary, *_hotspot_lines(data)])


def render_hotspots(data: Mapping[str, Any], top: int | None = None) -> str:
    """Ranked hotspots from a saved JSON report (the `report_to_dict` shape).

    `top` limits how many are printed; the header always states what the report holds, so a
    truncated view never reads as a clean session.
    """
    transcript_id = data.get("transcript_id", "?")
    total = len(data["hotspots"])
    if not total:
        return f"{transcript_id}: no hotspots."
    lines = _hotspot_lines(data, top)
    shown = f"{len(lines)} of {total}" if len(lines) != total else str(total)
    return "\n".join([f"{transcript_id}: {shown} hotspot(s)", *lines])
