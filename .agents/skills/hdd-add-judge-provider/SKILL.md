---
name: hdd-add-judge-provider
description: Use when adding a new judge backend (another System One vendor, a local model, a heuristic, or a cascade) to harness-drift-detector, so it plugs into the Judge port, keeps probability semantics uniform, and is selectable from the CLI.
---

# Adding a judge provider

A judge answers a batch of probes about one window state. The domain owns the questions and the meaning of the answers; the provider owns transport and translation. TypeSafe is one such provider ([decision](../../notes/implemented/architecture/2026-09-20-judge-port-with-typesafe-as-one-provider.md)).

## The port

```python
class Judge(Protocol):
    name: str  # CLI-facing id, e.g. "typesafe"
    model: str  # versioned model id reported in reports and used in cache keys

    async def judge(self, state: JsonValue, probes: Sequence[Probe]) -> JudgeResult: ...
```

`JudgeResult.judgments` maps every requested probe id to a `Judgment`. `probability` is P(drift) for a `NoulProbe` and `score / (len(levels) - 1)` for a `ScoreProbe`; `confidence` is the provider's confidence or `None`; `raw` keeps the provider payload for debugging. Raise on transport failure; never return a partial mapping.

## Steps

1. Create `src/harness_drift_detector/adapters/<name>_judge.py`. Import only `domain` modules and the provider SDK. Translate `NoulProbe.instructions` + `true_criteria`/`false_criteria` and `ScoreProbe.instructions` + `levels` into the provider's question form; keep the probe ids as the request keys.
2. Measure latency with `time.perf_counter()` and fill `Usage` from the provider response when available.
3. Write `tests/adapters/test_<name>_judge.py`: translation of probes to requests, translation of a hand-built response to judgments with the normalization above, and `judge()` against an injected fake client. If the provider needs a key, add a `live`-marked test that skips without it.
4. Register the provider in `cli.py`'s judge factory so `--judge <name>` selects it; `CachingJudge` wraps every provider unless `--no-cache`.
5. Name the provider in `docs/cli.md` under `--judge` and, if it changes a design assumption (for example a cascade that escalates flagged windows), an Agent Note.
6. Run `uv run pytest tests/adapters/test_<name>_judge.py tests/application/test_detect.py -q` and `uv run python scripts/verify_layering.py`.

## Do not

- Import the provider SDK anywhere outside its adapter and its tests.
- Change `Judgment` semantics per provider; thresholds in `DriftPolicy` assume P(drift).
- Put provider names or model ids in `domain/` or `application/`.
