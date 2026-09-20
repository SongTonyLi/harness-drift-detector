"""Drift report aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field

from .judgment import JudgeResult, Usage
from .policy import DriftPolicy, Hotspot
from .transcript import Transcript
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
    turns = number of distinct turns; steps = number of assistant events."""
    raise NotImplementedError
