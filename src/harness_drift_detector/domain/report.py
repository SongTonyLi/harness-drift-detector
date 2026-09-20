"""Drift report aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field

from .judgment import JudgeResult, Usage
from .policy import DriftPolicy, Hotspot, gate, rank
from .probes import CATALOG, NoulProbe
from .transcript import Transcript, TurnEndEvent
from .window import Window


@dataclass(frozen=True)
class WindowOutcome:
    window: Window
    result: JudgeResult | None
    error: str | None = None


@dataclass(frozen=True)
class ProbeStats:
    probe_id: str
    count: int
    mean: float
    max: float
    fired: int


@dataclass(frozen=True)
class DriftReport:
    transcript_id: str
    judge_name: str
    judge_model: str
    turns: int
    steps: int
    windows_judged: int
    windows_failed: int
    probes_asked: int
    wall_time_s: float
    usage: Usage
    probe_stats: tuple[ProbeStats, ...]
    hotspots: tuple[Hotspot, ...]
    outcomes: tuple[WindowOutcome, ...] = field(default_factory=tuple)
    policy: DriftPolicy = DriftPolicy()
    turns_interrupted: int = 0  # turns with steps that were aborted, errored, or never ended


def build_report(
    transcript: Transcript,
    outcomes: list[WindowOutcome],
    policy: DriftPolicy,
    judge_name: str,
    judge_model: str,
    wall_time_s: float,
) -> DriftReport:
    """Aggregate outcomes: gate each judged window, rank hotspots, compute per-probe stats
    (count/mean/max over judged windows; fired counts NoulProbes above threshold), sum usage.
    turns = number of distinct turns; steps = number of assistant events; turns_interrupted =
    turns with assistant steps whose turn_end reason is not "completed" (or absent)."""
    judged = 0
    failed = 0
    probes_asked = 0
    usage = Usage()
    probabilities: dict[str, list[float]] = {}
    fired_counts: dict[str, int] = {}
    hotspots: list[Hotspot] = []

    for outcome in outcomes:
        if outcome.error is not None or outcome.result is None:
            failed += 1
            continue
        judged += 1
        result = outcome.result
        usage = usage + result.usage
        for probe_id, judgment in result.judgments.items():
            probes_asked += 1
            probabilities.setdefault(probe_id, []).append(judgment.probability)
            fired_counts.setdefault(probe_id, 0)
            if isinstance(CATALOG.get(probe_id), NoulProbe) and (
                judgment.probability > policy.threshold_for(probe_id)
            ):
                fired_counts[probe_id] += 1
        hotspot = gate(outcome.window, result, policy)
        if hotspot is not None:
            hotspots.append(hotspot)

    known = [pid for pid in CATALOG if pid in probabilities]
    unknown = sorted(pid for pid in probabilities if pid not in CATALOG)
    probe_stats = tuple(
        ProbeStats(
            probe_id=probe_id,
            count=len(probabilities[probe_id]),
            mean=sum(probabilities[probe_id]) / len(probabilities[probe_id]),
            max=max(probabilities[probe_id]),
            fired=fired_counts[probe_id],
        )
        for probe_id in known + unknown
    )

    end_reasons = {e.turn: e.reason for e in transcript.events if isinstance(e, TurnEndEvent)}
    turns_with_steps = {step.turn for step in transcript.assistant_steps()}
    interrupted = sum(1 for turn in turns_with_steps if end_reasons.get(turn) != "completed")

    return DriftReport(
        transcript_id=transcript.transcript_id,
        judge_name=judge_name,
        judge_model=judge_model,
        turns=len(transcript.turn_numbers()),
        steps=len(transcript.assistant_steps()),
        windows_judged=judged,
        windows_failed=failed,
        probes_asked=probes_asked,
        wall_time_s=wall_time_s,
        usage=usage,
        probe_stats=probe_stats,
        hotspots=tuple(rank(hotspots)),
        outcomes=tuple(outcomes),
        policy=policy,
        turns_interrupted=interrupted,
    )
