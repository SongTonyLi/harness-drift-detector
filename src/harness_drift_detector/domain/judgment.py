"""Judgments and the Judge port."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .probes import Probe
from .transcript import JsonValue


@dataclass(frozen=True)
class Judgment:
    probe_id: str
    probability: float  # P(drift) for Nouls; score / (levels - 1) for Scores
    confidence: float | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)  # provider payload, for debugging


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass(frozen=True)
class JudgeResult:
    judgments: Mapping[str, Judgment]  # keyed by probe id
    model: str
    usage: Usage = Usage()
    latency_s: float = 0.0
    cached: bool = False


class Judge(Protocol):
    """Answers a batch of probes about one state. Implementations: adapters only."""

    name: str
    model: str

    async def judge(self, state: JsonValue, probes: Sequence[Probe]) -> JudgeResult: ...
