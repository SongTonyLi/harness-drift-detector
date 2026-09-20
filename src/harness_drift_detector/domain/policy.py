"""Gating policy: thresholds live in code and are applied after judging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .judgment import JudgeResult, Judgment
from .probes import CATALOG, NoulProbe, Probe
from .window import Window

EXCERPT_CHARS = 200


@dataclass(frozen=True)
class DriftPolicy:
    fire_threshold: float = 0.7
    overrides: Mapping[str, float] = field(default_factory=dict)

    def threshold_for(self, probe_id: str) -> float:
        return self.overrides.get(probe_id, self.fire_threshold)


@dataclass(frozen=True)
class FiredProbe:
    probe_id: str
    probability: float
    threshold: float


@dataclass(frozen=True)
class Hotspot:
    transcript_id: str
    turn: int
    step: int
    seq: int
    fired: tuple[FiredProbe, ...]
    severity: float  # max fired probability
    drift_degree: float | None  # normalized drift.degree score, if asked
    excerpt: str  # first EXCERPT_CHARS of assistant text (or first tool call when no text)
    judgments: Mapping[str, Judgment]

    @property
    def window_id(self) -> str:
        return f"{self.transcript_id}:t{self.turn}:s{self.step}"


def gate(
    window: Window,
    result: JudgeResult,
    policy: DriftPolicy,
    catalog: Mapping[str, Probe] = CATALOG,
) -> Hotspot | None:
    """Max-style gate: a Hotspot when any NoulProbe judgment's probability > its threshold.
    ScoreProbes (drift.degree) never fire; they only fill `drift_degree`. `fired` is sorted
    by probability descending."""
    raise NotImplementedError


def rank(hotspots: list[Hotspot]) -> list[Hotspot]:
    """Sort by severity desc, then drift_degree desc (None last), then transcript_id, turn, step."""
    raise NotImplementedError
