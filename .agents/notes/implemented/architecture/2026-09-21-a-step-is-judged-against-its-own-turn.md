# Agent Note: A step is judged against its own turn

Status: implemented

## Problem

The first Claude Code corpus flagged 17.8% of steps against 7.3% for a comparable dsh corpus, and two structures in the window explained almost all of the difference rather than any difference in behaviour.

`user_request` was the latest human message before the step. When the user types while the assistant is working, the harness delivers that message inside the running turn, so every later step of the turn was measured against a request that did not exist when the work began. In one session the user asked where some authentication code lived while a publish was running; the assistant correctly finished publishing first, and eight of those steps scored `user.off_task` at 0.92 or above. Windows whose request arrived mid-turn fired `user.off_task` at 7.2% against 3.0% for windows whose request opened the turn.

`turn_evidence`, the bounded digest of the turn's earlier tool results, reached only the turn-ending step. But a long turn narrates as it goes, and those mid-turn reports claim what the turn has established so far. Of 479 `tool.unsupported_claim` hotspots, 386 were mid-turn narration and 364 saw exactly one tool result, because the only evidence a mid-turn step had was whatever the previous step happened to return. The probe was being asked to check a paragraph of claims against one command's output.

## Decision

A turn opens on the human message current when its first assistant step runs, and that message stays `user_request` for every step of the turn. Human messages that arrive after the turn opened are carried separately as `interjections`, oldest first, bounded by `Budget.interjection` and `Budget.interjections_max`. Every probe that judges a step against what the user asked (`user.off_task`, `tool.unjustified_call`, `goal.premature_stop`, `goal.unnecessary_question`, `drift.degree`) states that the request and the interjections are both things the user asked, so working toward either is on task. `earlier_requests` now means the human messages before the turn's request, not simply the ones before the latest message.

`turn_evidence` goes to any step whose text is non-empty, not only the turn-ending one. A step with no text claims nothing, so it still gets none, which keeps the state small where the digest would be dead weight.

## Alternatives considered

**Let the interjection become the request, and rely on `earlier_requests`.** This was the shipped behaviour and the corpus shows it does not work: the original task was already present in `earlier_requests` for those eight steps and the probe still read the interjection as the live task. A field named `user_request` is what a literal reader treats as the request, whatever sits beside it.

**Start a new turn at an interjection.** Tidy in the transcript, wrong in fact: the assistant never stopped, no turn boundary exists in the log, and the steps after the interjection are still finishing the earlier work. It would also make `ends_turn` and the interrupted-turn count fiction.

**Give `turn_evidence` to every step.** Simpler to state, but it spends up to six thousand characters on call-only steps that assert nothing, against the standing rule that a window carries only what a probe reads. Non-empty text is the same condition `tool.unsupported_claim` already uses.

**Raise the `tool.unsupported_claim` threshold instead.** It was the open option from the earlier evaluation. It hides the symptom at the cost of the real detections in the same band, and it would leave the judge answering a question the state cannot support. Evidence first, thresholds after.

## Consequences

A step is now measured against the request it was actually working on, and a claim is checked against the turn that produced it. The cost is a larger state on narration steps and one accepted blind spot: when an interjection tells the assistant to stop and do something else, continuing the original request no longer reads as off task, because the probe treats both as things the user asked. Catching a countermanded instruction needs its own probe rather than a reinterpretation of this one.
