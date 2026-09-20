# Architecture

`hdd` turns a harness session into a ranked list of drift hotspots. Code owns the workflow; a System One judge supplies the semantic judgments. This page is the current-state map; rationale lives in [Agent Notes](../.agents/notes/README.md) and the original design in [the spec](superpowers/specs/2026-09-20-harness-drift-detector-design.md).

## Layers

| Layer | Path | Imports | Owns |
| --- | --- | --- | --- |
| Domain | `src/harness_drift_detector/domain/` | standard library only | `Transcript` and events, `Window` and `Budget`, the probe `CATALOG` and `select_probes`, `Judgment`/`JudgeResult`/`Judge`, `DriftPolicy`/`gate`/`rank`, `DriftReport`/`build_report`, the ports |
| Application | `src/harness_drift_detector/application/` | domain | `ConvertSessions`, `DetectDrift` (async, bounded concurrency), renderers |
| Adapters | `src/harness_drift_detector/adapters/` | domain, SDKs | `DshSessionSource`, `JsonlTranscriptStore`, `TypeSafeJudge`, `HeuristicJudge`, `CachingJudge` + `FileJudgmentCache`, `FakeJudge`, scrubbing |
| CLI | `src/harness_drift_detector/cli.py` | everything | argument parsing and wiring |

`scripts/verify_layering.py` rejects imports that cross these lines.

## Data flow

```
harness storage ──DshSessionSource──▶ Transcript ──JsonlTranscriptStore──▶ <id>.jsonl
<id>.jsonl ──▶ Transcript ──build_windows──▶ Window per assistant step
Window ──select_probes──▶ Probe[] ──Judge.judge(window.to_state(), probes)──▶ JudgeResult
JudgeResult ──gate(policy)──▶ Hotspot | None ──build_report──▶ DriftReport ──render──▶ json / md / terminal
```

One judge call per window carries every applicable probe. Windows run concurrently under a semaphore. `CachingJudge` keys on model, state, and probes, so re-running with a new threshold is free.

## Canonical JSONL transcript

```json
{"kind":"transcript","transcript_id":"session-...","harness":"dsh","source_path":"...","model":"...","provider":"...","cwd":"...","created_at":1789756882954}
{"kind":"system","seq":7,"turn":1,"step":1,"text":"..."}
{"kind":"user","seq":8,"turn":1,"text":"...","origin":"human"}
{"kind":"user","seq":9,"turn":1,"text":"...","origin":"harness"}
{"kind":"assistant","seq":15,"turn":1,"step":1,"text":"","tool_calls":[{"call_id":"...","name":"bash","arguments":"{...}"}],"stop_reason":"toolUse"}
{"kind":"tool_result","seq":17,"turn":1,"step":1,"call_id":"...","name":"bash","text":"...","is_error":false}
{"kind":"turn_end","seq":30,"turn":1,"reason":"completed"}
```

`origin: "harness"` marks messages the harness injected (skill catalogs, runtime snapshots); windows ignore them. Provider replay blobs and request headers are dropped. Tool result text has ANSI sequences removed and credential patterns replaced by `[REDACTED_SECRET]`.

## Windows

One per assistant step: `user_request` (latest human message), `previous_message` (the user message for a turn's first step, otherwise the previous step's tool results), `previous_assistant_text`, and `assistant_step` (text, tool calls, `ends_turn`). `Budget` bounds each field with an explicit omitted-chars marker. The system prompt is never included.

## Probes

Nine probes in `domain/probes.py`: `user.off_task`, `adjacent.ignores_previous`, `adjacent.self_discontinuity`, `tool.unsupported_claim`, `tool.ignored_error`, `tool.unjustified_call`, `goal.premature_stop`, `goal.unnecessary_question` (Nouls, `true` means drift, each with a precondition) and `drift.degree` (a four-level Score used for ranking only). Wording follows the [SDE cascade cookbook](https://docs.typesafe.ai/cookbooks/sde_cascade): narrow, grounded in named state fields, criteria aligned with instructions.

## Gate and report

`DriftPolicy(fire_threshold=0.7, overrides)` fires a hotspot when any Noul probability exceeds its threshold (max-style). Hotspots rank by severity, then `drift.degree`. `DriftReport` carries counts, wall time, token usage, per-probe statistics, ranked hotspots, and every window outcome including failures.

## Extension points

- **Judge provider:** implement `Judge` (`name`, `model`, `async judge(state, probes) -> JudgeResult`) in `adapters/`, register in `cli.py`. See [hdd-add-judge-provider](../.agents/skills/hdd-add-judge-provider/SKILL.md).
- **Harness source:** implement `TranscriptSource` (`harness`, `list_ids()`, `load(id)`) in `adapters/`, add a `--harness` choice.
- **Probe:** add a `NoulProbe`/`ScoreProbe` to `CATALOG` with a precondition in `select_probes`, a domain test, and a README row.
