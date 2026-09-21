# CLI reference

`hdd` has three commands. Run any of them with `--help` for the live option list.

## `hdd convert`

```
hdd convert --harness {dsh,claude} --root DIR --out DIR [--ids ID ...] [--no-scrub]
```

Writes one canonical JSONL transcript per session into `--out` and lists the sessions it
skipped (a log with no conversation has no events). `--no-scrub` keeps credential patterns
in tool output; by default they are replaced with `[REDACTED_SECRET]` and ANSI escape
sequences are removed.

| harness | `--root` | what is read |
| --- | --- | --- |
| `dsh` | `~/.dsh/sessions/<encoded-cwd>` | every `session-<uuid>` directory: raw `session.v3.jsonl` or the zstd-compressed default |
| `claude` | `~/.claude/projects/<encoded-cwd>` | every `<session-uuid>.jsonl` file. The streamed records of one response become one step; prompts queued while the assistant worked count as human messages; skill bodies, compaction summaries, task notifications, and local-command output keep origin `harness`. A turn ends at the `turn_duration` record, at a `[Request interrupted by user]` message (aborted), or at a synthetic API-error message (error); logs from versions without `turn_duration` complete a turn whose last step stopped with `end_turn`. Subagent transcripts under `<session-uuid>/subagents/` are not read. |

## `hdd detect`

```
hdd detect PATHS... --judge {typesafe,heuristic} [--model jev-latest] [--out reports]
           [--threshold 0.7] [--override PROBE=THRESHOLD ...] [--concurrency 8]
           [--probes id,id,...] [--no-cache] [--cache-dir .hdd-cache]
```

| flag | meaning |
| --- | --- |
| `--judge` | required; `typesafe` returns calibrated probabilities, which the default threshold is set for. `heuristic` is an offline lexical baseline (`user.off_task` is `1 - jaccard(request, step)`, a distance, not a probability) for smoke tests and wiring a new harness. |
| `--model` | model name sent to the judge; default `jev-latest`. Pass a pinned id such as `jev-1.13.0` for reproducible numbers. |
| `--threshold` | firing threshold for every Noul probe. |
| `--override` | firing threshold for one probe, repeatable: `--override tool.unsupported_claim=0.9`. |
| `--concurrency` | judge calls in flight across the whole batch. |
| `--probes` | ask only these probe ids; an unknown id exits 2. |
| `--no-cache`, `--cache-dir` | judgments are cached on disk by a content hash of model name, state, and probe wording. Changing only a threshold costs nothing; a cached window reports zero tokens and latency. The hash uses the model name you passed, so with the `jev-latest` alias a cached judgment survives a new release behind that alias. |

Writes `<transcript-id>.json` (the full report: every window's state and judgments, ranked
hotspots, per-probe statistics, usage) and `<transcript-id>.md` (summary tables) into `--out`,
and prints a terminal summary per transcript.

## `hdd hotspots`

```
hdd hotspots REPORT.json [--top N]
```

Prints the ranked hotspots of a saved report.

## Exit codes

`0` on success (a window the judge could not answer is recorded in the report, not raised),
`1` when no transcript could be read, `2` for a usage error or a missing `TYPESAFE_API_KEY`
with `--judge typesafe`.

## Tests

```bash
uv run pytest -q                      # unit + integration, no network
uv run pytest -q -m "not integration" # unit only
uv run pytest -q -m live              # one real TypeSafe call; needs TYPESAFE_API_KEY
```

Tests build their own synthetic session fixtures; no personal transcript is committed.
`data/`, `reports/`, and `.hdd-cache/` are gitignored.
