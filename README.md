# harness-drift-detector (`hdd`)

Fast drift hotspotting for coding-agent harness transcripts. `hdd` converts a harness's raw
session log into a canonical JSONL transcript, scores every assistant step on a handful of
alignment questions, and ranks the steps where the assistant stopped lining up with the work.

The point is triage: instead of reading a 400-step session, read the five steps the detector
flags.

## What "drift" means here

Drift is a step that stops lining up with something it should line up with:

| Dimension | The step should line up with |
| --- | --- |
| user | what the person asked for in the current turn |
| adjacent | the message it is directly answering (the user, or the tool results it just got) |
| tool | what the tool results actually say |
| goal | finishing the turn's goal instead of stopping or asking early |

Every probe is phrased so that `true` means drift, and each is asked only when its
precondition holds:

| Probe id | Type | Asked when | Question |
| --- | --- | --- | --- |
| `user.off_task` | Noul | always | Does the step fail to work toward `user_request`? |
| `adjacent.ignores_previous` | Noul | always | Does the step ignore or contradict `previous_message`? |
| `adjacent.self_discontinuity` | Noul | previous assistant text exists | Does the step abandon the assistant's own stated plan without saying why? |
| `tool.unsupported_claim` | Noul | responding to tool results, step has text | Does the step assert something the results do not support? |
| `tool.ignored_error` | Noul | a result is an error or matches an error marker | Does the step proceed past the failure without acknowledging it? |
| `tool.unjustified_call` | Noul | the step calls tools | Are the calls unrelated to the request and to the previous message? |
| `goal.premature_stop` | Noul | the step ends the turn | Does it stop with the request unfulfilled and no reason given? |
| `goal.unnecessary_question` | Noul | the step asks the user | Is the question already answered, or answerable by the assistant? |
| `drift.degree` | Score | always | How far has the step drifted? (on task / minor tangent / substantially off / unrelated) |

A window is a **hotspot** when any Noul probe's probability passes its threshold (a max-style
gate, never a mean). `drift.degree` never fires a hotspot; it only orders them.

## Quick start

```bash
uv sync

# 1. Convert harness sessions into canonical JSONL (personal data stays in gitignored data/)
uv run hdd convert --harness dsh --root ~/.dsh/sessions/<encoded-cwd> --out data/transcripts

# 2a. Judge with TypeSafe's System One model (the judge the thresholds are set for)
export TYPESAFE_API_KEY=...        # read from the environment only, never stored by hdd
uv run hdd detect data/transcripts/*.jsonl --judge typesafe --out reports

# 2b. Judge offline, no network, no key (a lexical baseline; see the note below)
uv run hdd detect data/transcripts/*.jsonl --judge heuristic --out reports

# 3. Re-read the ranked hotspots of a saved report
uv run hdd hotspots reports/<transcript-id>.json --top 10
```

`--judge` has no default on purpose: the two judges are not interchangeable. `typesafe`
returns calibrated probabilities, which is what the 0.7 firing threshold is set for.
`heuristic` is an offline lexical baseline that exists to prove the port and to run with no
network: `user.off_task` is `1 - jaccard(user request, step)`, a similarity distance rather
than a probability, and it sits above 0.8 for most real steps. Use it for smoke tests and
for wiring up a new harness, not for triage.

`hdd detect` writes `<transcript-id>.json` (the full report) and `<transcript-id>.md`
(summary tables) per transcript and prints a compact terminal summary. Useful flags:
`--threshold 0.7`, `--concurrency 8`, `--probes user.off_task,tool.ignored_error`,
`--no-cache`, `--cache-dir .hdd-cache`. Judgments are cached on disk by a content hash of
model name, state, and probe wording, so changing only the threshold costs nothing. The hash
uses the model *name* you passed: with the `jev-latest` alias, a cached judgment survives a
new release of the model behind that alias, so pass a pinned id (`--model jev-1.13.0`) or
clear `--cache-dir` when you want the numbers to be reproducible against one model version.
A cached window reports zero tokens and zero latency, because a re-run spends neither.

Exit codes: `0` on success (a window the judge could not answer is recorded in the report,
not raised), `1` when no transcript could be read, `2` for a usage error (an unknown
`--probes` id among them) or a missing `TYPESAFE_API_KEY` with `--judge typesafe`.

## Canonical JSONL transcript

One header line, then one event per line in `seq` order:

```json
{"kind":"transcript","transcript_id":"session-...","harness":"dsh","source_path":"...","model":"...","provider":"...","cwd":"/Users/x","created_at":1789756882954}
{"kind":"system","seq":7,"turn":1,"step":1,"text":"..."}
{"kind":"user","seq":8,"turn":1,"text":"...","origin":"human"}
{"kind":"assistant","seq":15,"turn":1,"step":1,"text":"","tool_calls":[{"call_id":"...","name":"bash","arguments":"{...}"}],"stop_reason":"toolUse"}
{"kind":"tool_result","seq":17,"turn":1,"step":1,"call_id":"...","name":"bash","text":"...","is_error":false}
{"kind":"turn_end","seq":30,"turn":1,"reason":"completed"}
```

`origin: "human"` marks what the person typed; `origin: "harness"` marks harness-injected
messages (skill catalogs, runtime context), which are never used as the user's request.
Provider replay state, reasoning blobs, and request headers are dropped, ANSI escapes are
stripped, and obvious secrets are replaced with `[REDACTED_SECRET]` before anything is written.

## Architecture

```
domain/       pure: transcript, windows, probe catalog, judgments, policy, report, ports
application/  use cases: ConvertSessions, DetectDrift, renderers
adapters/     dsh source, JSONL store, TypeSafe judge, heuristic judge, caching judge, fake judge
cli.py        wires adapters into use cases
```

`domain` imports nothing from the other layers; `application` imports `domain` only;
`adapters` implement the ports; `cli` does the wiring and imports adapters lazily.

The unit of judgment is a **window**: one assistant step plus the minimal context needed to
judge it (the human request, the message it is answering, its own previous text, and the step
itself). Each field is bounded by a `Budget` with explicit `[... N chars omitted ...]`
markers, because System One accuracy degrades on large state. Long fields keep their head
and their tail, so the end of a step (its conclusions, its closing question) and a failure
buried in the middle of a long tool result both survive the budget. All probes for one
window go in a single call, and windows run concurrently under a semaphore.

## Adding a judge provider

Implement the `Judge` port from `domain/judgment.py`:

```python
class MyJudge:
    name = "my-provider"
    model = "my-model-1"

    async def judge(self, state, probes) -> JudgeResult: ...
```

Translate each `NoulProbe` into a yes/no question with explicit true/false criteria and each
`ScoreProbe` into an ordered level scale (probability = `score / (len(levels) - 1)`). Return
one `Judgment` per probe id, plus the model name, token usage, and latency. Then add the name
to the `--judge` choices and to `_build_judge` in `cli.py`. Wrapping it in `CachingJudge` is
free.

## Adding a harness

Implement the `TranscriptSource` port from `domain/ports.py` (`harness`, `list_ids()`,
`load(id)`) so it returns a `Transcript` in the canonical shape, then add it to `--harness`
in `cli.py`. Nothing else changes: windowing, probes, policy, report, and renderers are
harness-agnostic.

## Tests

```bash
uv run pytest -q                      # unit + integration
uv run pytest -q -m "not integration" # unit only
uv run pytest -q -m live              # one real TypeSafe call; needs TYPESAFE_API_KEY
```

Tests build their own synthetic session fixtures; no personal transcript is committed.
`data/`, `reports/`, and `.hdd-cache/` are gitignored.

## Validation

One run over the author's own `~/.dsh/sessions` directory, judged with TypeSafe
(`jev-latest`, resolved to `jev-1.13.0`) at the default threshold of 0.7. Counts only.

| metric | value |
| --- | --- |
| sessions found | 10 |
| sessions converted | 5 |
| sessions skipped (header only, no events) | 5 |
| windows judged | 24 |
| windows failed | 0 |
| probes asked | 109 |
| hotspots | 5 |
| mean latency per window | 0.43s |
| tokens (in / out) | 27529 / 2142 |

## License

Distributed under the GNU General Public License, version 3 or later
(`GPL-3.0-or-later`). The full text is in [LICENSE](LICENSE).
