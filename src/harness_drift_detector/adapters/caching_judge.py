"""Content-hash disk cache around any Judge."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..domain.judgment import Judge, JudgeResult, Judgment, Usage
from ..domain.ports import JudgmentCache
from ..domain.probes import Probe
from ..domain.transcript import JsonValue


def cache_key(model: str, state: JsonValue, probes: Sequence[Probe]) -> str:
    """sha256 over the model, the state, and the probes (wording included), so a reworded
    probe or a changed state is a miss while a re-run with a new threshold is a hit."""
    payload = json.dumps(
        {
            "model": model,
            "state": state,
            "probes": [dataclasses.asdict(probe) for probe in probes],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def result_to_dict(result: JudgeResult) -> dict[str, Any]:
    return dataclasses.asdict(result)


def result_from_dict(data: dict[str, Any]) -> JudgeResult:
    judgments = {
        probe_id: Judgment(
            probe_id=judgment["probe_id"],
            probability=judgment["probability"],
            confidence=judgment.get("confidence"),
            raw=judgment.get("raw") or {},
        )
        for probe_id, judgment in (data.get("judgments") or {}).items()
    }
    usage = data.get("usage") or {}
    return JudgeResult(
        judgments=judgments,
        model=data["model"],
        usage=Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
        latency_s=data.get("latency_s", 0.0),
        cached=data.get("cached", False),
    )


class FileJudgmentCache:
    """One `<key>.json` file per judged window. An unreadable entry counts as a miss."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> JudgeResult | None:
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return result_from_dict(data)
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    def put(self, key: str, result: JudgeResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(
            json.dumps(result_to_dict(result), ensure_ascii=False), encoding="utf-8"
        )


class CachingJudge:
    """Decorates a Judge: returns a stored JudgeResult (with `cached=True`) when the model,
    state, and probes match a previous call.

    The cache is an optimisation: a hit reports no usage and no latency, because this run
    spent neither, and a failing write never loses a judgment that was already paid for.
    """

    def __init__(self, inner: Judge, cache: JudgmentCache) -> None:
        self.inner = inner
        self.cache = cache
        self.name = inner.name
        self.model = inner.model

    async def judge(self, state: JsonValue, probes: Sequence[Probe]) -> JudgeResult:
        key = cache_key(self.model, state, probes)
        hit = self.cache.get(key)
        if hit is not None:
            return dataclasses.replace(hit, cached=True, usage=Usage(), latency_s=0.0)
        result = await self.inner.judge(state, probes)
        with contextlib.suppress(Exception):  # a write failure never discards a judgment made
            self.cache.put(key, result)
        return result

    async def aclose(self) -> None:
        close = getattr(self.inner, "aclose", None)
        if close is not None:
            await close()
