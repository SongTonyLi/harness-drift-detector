"""Content-hash caching around any Judge."""

import dataclasses
import json

from harness_drift_detector.adapters.caching_judge import (
    CachingJudge,
    FileJudgmentCache,
    cache_key,
)
from harness_drift_detector.adapters.fake_judge import FakeJudge
from harness_drift_detector.domain.judgment import JudgeResult, Judgment, Usage
from harness_drift_detector.domain.probes import CATALOG

PROBES = [CATALOG["user.off_task"], CATALOG["drift.degree"]]
STATE = {"user_request": "list the files", "assistant_step": {"text": "ok"}}


def _result() -> JudgeResult:
    return JudgeResult(
        judgments={
            "user.off_task": Judgment("user.off_task", 0.9, None, {"noul": 0.9}),
            "drift.degree": Judgment("drift.degree", 0.66, 0.8, {"score": 2.0}),
        },
        model="fake",
        usage=Usage(30, 4),
        latency_s=0.25,
    )


def test_cache_key_is_stable_for_equal_inputs():
    assert cache_key("jev-latest", STATE, PROBES) == cache_key("jev-latest", dict(STATE), list(PROBES))


def test_cache_key_ignores_key_order_in_the_state():
    reordered = {"assistant_step": {"text": "ok"}, "user_request": "list the files"}
    assert cache_key("jev-latest", STATE, PROBES) == cache_key("jev-latest", reordered, PROBES)


def test_cache_key_changes_with_model_state_and_probe_wording():
    base = cache_key("jev-latest", STATE, PROBES)

    assert cache_key("jev-1.13.0", STATE, PROBES) != base
    assert cache_key("jev-latest", {"user_request": "other"}, PROBES) != base
    assert cache_key("jev-latest", STATE, [PROBES[0]]) != base

    reworded = dataclasses.replace(PROBES[0], instructions="Is the step off task, really?")
    assert cache_key("jev-latest", STATE, [reworded, PROBES[1]]) != base


def test_file_cache_miss_returns_none(tmp_path):
    assert FileJudgmentCache(tmp_path / "cache").get("deadbeef") is None


def test_file_cache_round_trips_a_result(tmp_path):
    cache = FileJudgmentCache(tmp_path / "cache")

    cache.put("k1", _result())

    assert cache.get("k1") == _result()
    assert json.loads((tmp_path / "cache" / "k1.json").read_text())["model"] == "fake"


def test_file_cache_treats_an_unreadable_entry_as_a_miss(tmp_path):
    cache = FileJudgmentCache(tmp_path / "cache")
    cache.put("k1", _result())
    (tmp_path / "cache" / "k1.json").write_text("{not json")

    assert cache.get("k1") is None


async def test_caching_judge_misses_then_hits(tmp_path):
    inner = FakeJudge({"user.off_task": 0.9})
    judge = CachingJudge(inner, FileJudgmentCache(tmp_path / "cache"))

    first = await judge.judge(STATE, PROBES)
    second = await judge.judge(dict(STATE), list(PROBES))

    assert judge.name == "fake" and judge.model == "fake"
    assert len(inner.calls) == 1
    assert first.cached is False
    assert second.cached is True
    assert second.judgments == first.judgments
    assert second.model == first.model


async def test_caching_judge_calls_inner_for_a_new_state(tmp_path):
    inner = FakeJudge({})
    judge = CachingJudge(inner, FileJudgmentCache(tmp_path / "cache"))

    await judge.judge(STATE, PROBES)
    await judge.judge({"user_request": "something else"}, PROBES)

    assert len(inner.calls) == 2


async def test_caching_judge_closes_the_inner_judge(tmp_path):
    class Closable(FakeJudge):
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    inner = Closable({})
    judge = CachingJudge(inner, FileJudgmentCache(tmp_path / "cache"))

    await judge.aclose()

    assert inner.closed is True


def test_file_cache_treats_json_that_is_not_an_object_as_a_miss(tmp_path):
    cache = FileJudgmentCache(tmp_path / "cache")
    cache.put("k1", _result())
    (tmp_path / "cache" / "k1.json").write_text("[]")

    assert cache.get("k1") is None


async def test_a_failing_cache_write_still_returns_the_judgment(tmp_path):
    class BrokenCache:
        def get(self, key):
            return None

        def put(self, key, result):
            raise OSError("read-only file system")

    inner = FakeJudge({"user.off_task": 0.9})
    judge = CachingJudge(inner, BrokenCache())

    result = await judge.judge(STATE, PROBES)

    assert result.judgments["user.off_task"].probability == 0.9
    assert len(inner.calls) == 1


async def test_a_cache_hit_reports_no_spend(tmp_path):
    cache = FileJudgmentCache(tmp_path / "cache")
    cache.put(cache_key("fake", STATE, PROBES), _result())
    judge = CachingJudge(FakeJudge({}), cache)

    hit = await judge.judge(STATE, PROBES)

    assert hit.cached is True
    assert hit.usage == Usage()  # nothing was spent on this run
    assert hit.latency_s == 0.0
    assert hit.judgments == _result().judgments
