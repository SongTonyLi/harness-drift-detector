# Agent Note: Drift probes follow the SDE cascade verifier design

Status: implemented

## Problem

A single "is this step good?" judgment is mushy and uncalibrated, hides which kind of drift occurred, and averages one confident red flag into silence. The detector must localize drift to a dimension (user request, adjacent message, tool results, turn goal), stay cheap enough to run on every step, and let thresholds be tuned without rerunning inference.

## Decision

Probes in `domain/probes.py` follow the verifier design from TypeSafe's SDE cascade cookbook. Each Noul asks one narrow, grounded question about named state fields, framed so `true` means drift, with explicit `true_criteria` and `false_criteria` aligned to the instructions. Each probe has a precondition in `select_probes` (for example `tool.ignored_error` only when a previous tool result shows an error marker), so a request carries only applicable questions. All probes for one window travel in one request. `gate` in `domain/policy.py` is max-style: a window is a hotspot when any Noul exceeds its threshold; probabilities are never averaged. The one Score, `drift.degree`, ranks hotspots and never fires one. Windows carry only the fields probes reference, bounded by `Budget`, because System One accuracy falls with irrelevant state.

## Window context and preconditions

A probe is only as good as the state it reads, and a run over 74 sessions showed four ways the first window design asked questions the state could not answer. Each tool result now carries the call's `input`, because an exit code means nothing without its command. A turn-ending step sees `turn_evidence`, a bounded digest of the turn's earlier results, because a summary claims things the previous step alone did not establish. Every window carries `earlier_requests`, because a follow-up such as "continue" hides the task it continues. Bookkeeping tools (`send_message`, `todo_write`, `list_agents`, `skill`, and the like) are never evidence and never a failure to handle. And `turn_end_reason` separates a turn the assistant chose to end from one the harness aborted or that errored: only the former is asked `goal.premature_stop`; the latter are counted as interrupted in the report. A call-only step is not asked `user.off_task`; its call is judged by `tool.unjustified_call`, which stays calibrated where raw arguments against the request do not.

## Alternatives considered

**One holistic judge per step.** Cheapest to write, but the cookbook's own data shows the overall head sits in the middle of the distribution while per-field heads separate cleanly; a holistic score also cannot tell a reviewer where to look.

**Mean of probe probabilities as the hotspot score.** Averages a 0.95 unsupported-claim with six 0.1 answers into 0.22 and misses the hotspot. Max keeps one confident flag decisive; the mean remains available in report statistics.

**Free-text reasoning model as the judge.** Better at indirection, but slow and expensive per step and it returns prose the code must parse. Escalating flagged windows to a reasoning model is a natural future rung behind the same port.

**Include the system prompt in every window.** Would let a probe check instruction adherence, but the prompt is thousands of tokens of mostly irrelevant rules and would degrade every other probe. An instruction-adherence probe needs a filtered rule excerpt and is deferred.

## Consequences

Hotspots name the dimension that fired and the evidence field it read. Thresholds are plain numbers in `DriftPolicy` and can be swept over cached judgments. Adding a dimension is one catalog entry plus a precondition and a test. The cost is a larger question set per window and the need to keep criteria wording literal, since the model answers the question as written.
