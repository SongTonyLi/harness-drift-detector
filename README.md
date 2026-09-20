# harness-drift-detector (`hdd`)

Find the steps where a coding agent stopped doing what it was asked. `hdd` turns a harness's
session log into a transcript, asks a fast System One judge (TypeSafe's Jev) a few narrow
questions about every assistant step, and ranks the steps that fail them. Read the five
flagged steps instead of the 400-step session.

## What it looks for

Each probe is a yes/no question phrased so that `true` means drift, asked only when the step
gives it something to judge:

| Probe | Fires when the step... |
| --- | --- |
| `user.off_task` | stops working toward the user's request without saying why it cannot |
| `adjacent.ignores_previous` | ignores or contradicts the message it is answering |
| `adjacent.self_discontinuity` | drops its own stated plan without explanation |
| `tool.unsupported_claim` | asserts an outcome the tool results do not support |
| `tool.ignored_error` | walks past a tool failure without mentioning or handling it |
| `tool.unjustified_call` | calls tools unrelated to the request and the previous message |
| `goal.premature_stop` | ends a completed turn with the request unfulfilled and no reason given |
| `goal.unnecessary_question` | asks something already answered, or answerable by itself |

A ninth probe, `drift.degree`, scores how far the step drifted and only orders the results.
A step is a **hotspot** when any probe passes its threshold (default 0.7): a max gate, never
a mean, so one confident flag is enough. Thresholds live in code and can be swept over cached
judgments without paying for inference again.

## Quick start

```bash
uv sync
uv run hdd convert --harness dsh --root ~/.dsh/sessions/<encoded-cwd> --out data/transcripts
export TYPESAFE_API_KEY=...    # read from the environment only, never stored
uv run hdd detect data/transcripts/*.jsonl --judge typesafe --out reports
uv run hdd hotspots reports/<transcript-id>.json --top 10
```

`detect` writes a JSON report and a Markdown summary per transcript and prints the ranked
hotspots. `--judge heuristic` is an offline lexical baseline for wiring and smoke tests, not
for triage. Every flag, the cache, and the exit codes are in [docs/cli.md](docs/cli.md).

## Does it work

On the author's own sessions, judged with `jev-1.13.0` at the default threshold:

| corpus | windows | hotspots | what they were |
| --- | --- | --- | --- |
| 5 sessions | 24 | 2 | exactly the two steps a reader marks as drift, at 0.88 to 0.94; no other probe above 0.58 |
| 74 sessions | 4,068 | 295 (7.3%) | plus 35 interrupted turns reported separately; two thirds of the hotspots are `tool.unsupported_claim` on narration steps and long final summaries, a triage choice tunable with `--override tool.unsupported_claim=0.9` |

A session takes about a second; the 74-session run spent 8M input tokens, roughly a third of
a dollar at Jev's published rate. The first window design flagged 16.7% of steps; the drop to
7.3% came from showing the judge each tool call's input, the session's earlier requests, only
real-tool results as evidence, and how each turn ended, not from tuning the model.

## How it is built

Domain-driven, so the judge is a port and TypeSafe is one provider behind it:

```
domain/       pure: transcript, windows, probe catalog, judgments, policy, report, ports
application/  use cases: convert, detect, render
adapters/     dsh session source, JSONL store, TypeSafe / heuristic / caching / fake judges
cli.py        wiring
```

A window carries only what a probe reads: the request and the session's earlier requests,
the message being answered with each tool call's input and output, the step itself, and for
a turn-ending step a bounded digest of the turn's evidence. All probes for a window go in
one call; windows run concurrently. The transcript format, the layers, and the extension
points for a new judge or harness are in [docs/architecture.md](docs/architecture.md).
Contributors and agents start at [AGENTS.md](AGENTS.md); decisions are recorded under
[.agents/notes](.agents/notes/README.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
