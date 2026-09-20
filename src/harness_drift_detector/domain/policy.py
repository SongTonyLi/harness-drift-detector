"""Gating policy: thresholds live in code and are applied after judging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .judgment import JudgeResult, Judgment
from .probes import CATALOG, NoulProbe, Probe, ScoreProbe
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
    fired: list[FiredProbe] = []
    for probe_id, judgment in result.judgments.items():
        if not isinstance(catalog.get(probe_id), NoulProbe):
            continue
        threshold = policy.threshold_for(probe_id)
        if judgment.probability > threshold:
            fired.append(FiredProbe(probe_id, judgment.probability, threshold))
    if not fired:
        return None
    fired.sort(key=lambda f: (-f.probability, f.probe_id))

    drift_degree: float | None = None
    for probe_id, probe in catalog.items():
        if isinstance(probe, ScoreProbe) and probe_id in result.judgments:
            drift_degree = result.judgments[probe_id].probability
            break

    return Hotspot(
        transcript_id=window.transcript_id,
        turn=window.turn,
        step=window.step,
        seq=window.seq,
        fired=tuple(fired),
        severity=max(f.probability for f in fired),
        drift_degree=drift_degree,
        excerpt=_excerpt(window),
        judgments=result.judgments,
    )


def _excerpt(window: Window) -> str:
    if window.assistant_text.strip():
        return window.assistant_text[:EXCERPT_CHARS]
    if window.tool_calls:
        call = window.tool_calls[0]
        return f"{call.tool} {call.arguments}"[:EXCERPT_CHARS]
    return ""


def rank(hotspots: list[Hotspot]) -> list[Hotspot]:
    """Sort by severity desc, then drift_degree desc (None last), then transcript_id, turn, step."""
    return sorted(
        hotspots,
        key=lambda h: (
            -h.severity,
            h.drift_degree is None,
            -(h.drift_degree if h.drift_degree is not None else 0.0),
            h.transcript_id,
            h.turn,
            h.step,
        ),
    )
