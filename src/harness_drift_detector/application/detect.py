"""DetectDrift: windows -> probes -> judge -> gate -> report, with bounded concurrency."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Sequence

from ..domain.judgment import Judge
from ..domain.policy import DriftPolicy
from ..domain.probes import Probe, select_probes
from ..domain.report import DriftReport, WindowOutcome, build_report
from ..domain.transcript import Transcript
from ..domain.window import Budget, Window, build_windows


@dataclass(frozen=True)
class DetectOptions:
    policy: DriftPolicy = DriftPolicy()
    budget: Budget = Budget()
    concurrency: int = 8
    only_probes: set[str] | None = None


class DetectDrift:
    """Judges every assistant step of a transcript and aggregates a DriftReport."""

    def __init__(self, judge: Judge, options: DetectOptions = DetectOptions()) -> None:
        self.judge = judge
        self.options = options

    async def run(self, transcript: Transcript) -> DriftReport:
        return await self._run(transcript, asyncio.Semaphore(self.options.concurrency))

    async def run_many(self, transcripts: Sequence[Transcript]) -> list[DriftReport]:
        """All transcripts share one semaphore, so the judge sees at most `concurrency`
        calls in flight across the whole batch."""
        semaphore = asyncio.Semaphore(self.options.concurrency)
        return list(await asyncio.gather(*(self._run(t, semaphore) for t in transcripts)))

    async def _run(self, transcript: Transcript, semaphore: asyncio.Semaphore) -> DriftReport:
        started = time.perf_counter()
        batches = []
        for window in build_windows(transcript, self.options.budget):
            probes = select_probes(window, self.options.only_probes)
            if probes:
                batches.append((window, probes))
        outcomes = list(
            await asyncio.gather(*(self._judge_window(w, p, semaphore) for w, p in batches))
        )
        return build_report(
            transcript=transcript,
            outcomes=outcomes,
            policy=self.options.policy,
            judge_name=self.judge.name,
            judge_model=self.judge.model,
            wall_time_s=time.perf_counter() - started,
        )

    async def _judge_window(
        self, window: Window, probes: Sequence[Probe], semaphore: asyncio.Semaphore
    ) -> WindowOutcome:
        async with semaphore:
            try:
                result = await self.judge.judge(window.to_state(), probes)
            except Exception as exc:  # a judge failure is data, not a crash
                return WindowOutcome(window=window, result=None, error=repr(exc))
        return WindowOutcome(window=window, result=result)
