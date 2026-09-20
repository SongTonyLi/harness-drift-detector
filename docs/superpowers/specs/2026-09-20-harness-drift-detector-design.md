# Harness Drift Detector: design

Date: 2026-09-20

## Goal

Fast detection of *drift* in a coding-agent harness's outputs, so a person can jump straight
to the hotspots of a session instead of reading the whole transcript. Drift means the
assistant's step stops lining up with something it should line up with: the user's request,
the message it is directly answering, the tool results it just received, or the goal of the
turn.

The first harness is DeepSeek Harness (`dsh`), whose sessions live under
`~/.dsh/sessions/<encoded-cwd>/session-<uuid>/session.v3.jsonl(.zstd)`. The first judge is
TypeSafe's System One model (Jev). Both are adapters; the domain does not know about either.

## Assumptions (made without a blocking question)

- Personal session transcripts are converted into a gitignored `data/` directory and are not
  committed to the public repository. The repository ships a small synthetic fixture instead.
- The TypeSafe key is read only from the `TYPESAFE_API_KEY` environment variable.
- Python 3.12 with `uv`; the SDK is `typesafe-sdk` (0.7.x, model alias `jev-latest`, which
  resolves to `jev-1.13.0` today).
- Commit and PR messages carry no AI attribution of any kind.

## Ubiquitous language

| Term | Meaning |
| --- | --- |
| Transcript | One harness session, normalized. Header plus an ordered list of events. |
| Event | One canonical JSONL line: `system`, `user`, `assistant`, `tool_result`, `turn_end`. |
| Turn | One user request and everything the assistant did until it yielded. |
| Step | One assistant message (text and/or tool calls) plus the results of those calls. |
| Window | The unit of judgment: one assistant step with the minimal context needed to judge it. |
| Dimension | An alignment axis (user alignment, adjacent alignment, tool alignment, goal). |
| Probe | One narrow question, built from a dimension and a window, framed so that `true` means drift. |
| Judgment | The probability (0..1) that a probe's drift condition holds, plus optional confidence. |
| Judge | The port that answers probes. TypeSafe is one implementation. |
| Policy | Thresholds and gating rules, owned by code, applied after judging. |
| Hotspot | A window where at least one probe fired above its threshold. |
| Drift report | All judgments for a transcript, the hotspots, and per-dimension statistics. |

## Bounded context and layering

```
src/harness_drift_detector/
  domain/          pure Python, no I/O, no SDK imports
    transcript.py  Transcript, events, TranscriptHeader
    window.py      Window, PreviousMessage, windowing (transcript -> windows), truncation Budget
    probes.py      Dimension enum, Probe types, probe catalog (build_probes(window))
    judgment.py    Judgment, JudgeResult, Judge port (Protocol)
    policy.py      DriftPolicy, Hotspot, gate(window, judgments) -> Hotspot | None
    report.py      DriftReport aggregate, per-dimension stats
    ports.py       TranscriptSource, TranscriptStore, JudgmentCache ports
  application/
    convert.py     ConvertSessions use case
    detect.py      DetectDrift use case (windows -> probes -> judge -> gate -> report), async, bounded concurrency
    render.py      report -> JSON / Markdown / terminal text
  adapters/
    dsh_source.py         DshSessionSource: reads v3 raw or zstd session logs
    jsonl_store.py        JsonlTranscriptStore: canonical JSONL read/write
    typesafe_judge.py     TypeSafeJudge: probes -> Noul/Score questions, answers -> judgments
    heuristic_judge.py    HeuristicJudge: offline lexical provider (no network)
    caching_judge.py      CachingJudge: content-hash disk cache around any Judge
    fake_judge.py         FakeJudge for tests (scripted answers)
  cli.py           `hdd convert`, `hdd detect`, `hdd hotspots`
```

Dependency rule: `domain` imports nothing from the other layers. `application` imports
`domain` only. `adapters` import `domain` (and third-party SDKs). `cli` wires adapters into
application use cases.

## Canonical JSONL transcript format

First line is the header, then one event per line in `seq` order.

```json
{"kind":"transcript","transcript_id":"session-...","harness":"dsh","source_path":"...","model":"gpt-5.6-terra","provider":"openai-codex","cwd":"/Users/x","created_at":1789756882954}
{"kind":"system","seq":7,"turn":1,"step":1,"text":"..."}
{"kind":"user","seq":8,"turn":1,"text":"...","origin":"human"}
{"kind":"user","seq":9,"turn":1,"text":"...","origin":"harness"}
{"kind":"assistant","seq":15,"turn":1,"step":1,"text":"","tool_calls":[{"call_id":"...","name":"bash","arguments":"{...}"}],"stop_reason":"toolUse"}
{"kind":"tool_result","seq":17,"turn":1,"step":1,"call_id":"...","name":"bash","text":"...","is_error":false}
{"kind":"turn_end","seq":30,"turn":1,"reason":"completed"}
```

- `origin: "human"` marks messages typed by the person; `origin: "harness"` marks messages the
  harness injected (skill catalogs, runtime-context snapshots). Windows use only human
  messages as `user_request`.
- Provider replay state, encrypted reasoning blobs, and request headers are dropped.
- `tool_result.text` joins the text blocks of the result; ANSI escape sequences are removed.
- A converter scrubs obvious secrets (`apikey_...`, `sk-...`, bearer tokens) with a fixed
  placeholder before writing.

## Windowing

One window per assistant step. Fields, each bounded by a `Budget` (head/tail truncation with
an explicit `[... N chars omitted ...]` marker):

| Field | Content |
| --- | --- |
| `user_request` | The human message that started the turn (latest human message before the step). |
| `previous_message` | What the step is directly responding to: `{"from":"user","text":...}` for the first step of a turn, or `{"from":"tools","results":[{"tool","is_error","text"}]}` for later steps. |
| `previous_assistant_text` | Text of the assistant's previous step in this turn, if any (empty otherwise). |
| `assistant_step` | `{"text":..., "tool_calls":[{"tool","arguments"}], "ends_turn": bool}` |

Default budget: `user_request` 4000 chars, each tool result 2400 chars (1600 head + 800
tail), `previous_assistant_text` 2000 chars, `assistant_step.text` 4000 chars, each
`arguments` 1200 chars. The system prompt is not sent; it is large and mostly irrelevant to
any single step (see the Jev jaggedness notes on large state).

## Probe catalog

All Nouls are framed so that `true` means drift, with explicit criteria, following the SDE
cascade cookbook. Conditional probes are only asked when their precondition holds, which
keeps every request narrow.

| Probe id | Type | Asked when | Question (state paths in backticks) |
| --- | --- | --- | --- |
| `user.off_task` | Noul | always | Does the `assistant_step` fail to work toward what the user asked in `user_request`? |
| `adjacent.ignores_previous` | Noul | always | Does the `assistant_step` ignore or contradict the content of `previous_message`, the message it is directly responding to? |
| `adjacent.self_discontinuity` | Noul | `previous_assistant_text` non-empty | Does the `assistant_step` abandon or contradict the plan stated in `previous_assistant_text` without saying why? |
| `tool.unsupported_claim` | Noul | `previous_message.from == "tools"` and step text non-empty | Does the `assistant_step` text assert an outcome, fact, or completed action that `previous_message.results` do not support? |
| `tool.ignored_error` | Noul | any previous result `is_error` or text contains an error marker | Do `previous_message.results` contain a failure that the `assistant_step` proceeds past without acknowledging or handling? |
| `tool.unjustified_call` | Noul | step has tool calls | Are the `assistant_step.tool_calls` unrelated to `user_request` and to what `previous_message` called for? |
| `goal.premature_stop` | Noul | `assistant_step.ends_turn` | Does the assistant end its turn while `user_request` is not fulfilled, without explaining why it stopped? |
| `goal.unnecessary_question` | Noul | step calls `ask_user_question` or ends the turn with a question | Does the `assistant_step` ask the user something already answered in `user_request` or `previous_message`, or something the assistant could have found out itself? |
| `drift.degree` | Score | always | How far has the `assistant_step` drifted from `user_request`? Levels: fully on task / minor tangent / substantially off / entirely unrelated. |

Error markers for `tool.ignored_error`: `[exit code: N]` with N not 0, `Traceback`,
`Error:`, `error:`, `FAILED`, `command not found`, `No such file`, `Permission denied`.

## Judging

`Judge` port: `async def judge(state: JsonValue, probes: Sequence[Probe]) -> JudgeResult`.
A `JudgeResult` holds judgments keyed by probe id, the judge's model name, token usage, and
latency. All probes for one window go in one call (speculative fan-out). Windows run
concurrently under a semaphore (default 8). A `CachingJudge` decorator keys on
`sha256(model, canonical JSON of state, canonical JSON of probes)` so re-running with a new
threshold costs nothing.

TypeSafe adapter: `Noul(instructions, criteria=NoulCriteria(true=..., false=...))` and
`Score(instructions, criteria=[levels])`. A Score judgment's probability is
`score / (len(levels) - 1)`; its confidence is the SDK's confidence.

Heuristic adapter (offline): `tool.ignored_error` from error markers and the absence of
acknowledgement words in the step text; `user.off_task` from token overlap between the user
request and the step; every other probe returns 0.5 with confidence 0. It exists to prove
the port and to run with no network.

## Policy and hotspots

`DriftPolicy(fire_threshold=0.7, overrides={probe_id: threshold})`. A window is a hotspot if
any Noul probe's probability exceeds its threshold (max-style gate, never a mean). Hotspots
are ranked by the highest fired probability, then by `drift.degree`. `drift.degree` alone
does not fire a hotspot; it orders them.

## Report

`DriftReport`: transcript id, judge model, counts (turns, steps, windows judged, probes
asked), wall time, token usage, per-probe statistics (count, mean, max, fired), and the
ranked hotspots. Each hotspot carries turn, step, fired probes with probabilities, all
judgments for that window, and a short excerpt of the assistant text. Renderers: JSON (the
full report), Markdown (summary tables), terminal text.

## CLI

```
hdd convert --harness dsh --root ~/.dsh/sessions/<encoded-cwd> --out data/transcripts
hdd detect data/transcripts/*.jsonl --judge typesafe --out reports [--threshold 0.7] [--concurrency 8] [--no-cache] [--probes user.off_task,...]
hdd hotspots reports/<transcript>.json [--top 10]
```

`hdd detect` prints the terminal summary and writes `<transcript_id>.json` and
`<transcript_id>.md` per transcript. Exit code is 0; failures to judge a window are recorded
in the report, not raised.

## Errors

- Unreadable or non-v3 session logs: skip with a warning listing the path; never abort a batch.
- Judge failure for one window (network, rate limit after SDK retries): the window is
  recorded with `error` and no judgments; the report counts it.
- Missing `TYPESAFE_API_KEY` with `--judge typesafe`: exit 2 with a one-line message.

## Testing

- Domain: windowing on a hand-built transcript, conditional probe selection, truncation with
  markers, gate and ranking, report statistics. No I/O.
- Converter: a synthetic v3 fixture (raw and zstd, generated in the test) covering human
  and harness user messages, tool calls, errors, and a two-turn session. Secret scrubbing.
- TypeSafe adapter: probe-to-question translation and response-to-judgment translation
  against SDK response objects; one `live` test that runs only with a key present.
- Application: `DetectDrift` with `FakeJudge`, verifying batching per window and concurrency.
- End-to-end: `hdd convert` and `hdd detect --judge heuristic` on the fixture.
- Validation on the author's real sessions is run locally and summarized in the README with
  counts only.

## Out of scope

Live streaming of a running session, other harness formats, a web UI, and tuning thresholds
against labeled data. All are natural extensions behind the existing ports.
