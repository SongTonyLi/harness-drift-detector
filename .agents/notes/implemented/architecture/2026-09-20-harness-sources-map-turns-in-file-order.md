# Agent Note: Harness sources read their log in file order and map turn ends themselves

Status: implemented

## Problem

The canonical transcript has turns, steps, human and harness user messages, and a `turn_end` with a reason, because the windows and probes depend on them: `user_request` is the latest human message, `goal.premature_stop` is asked only on a completed turn, and interrupted turns are reported apart. A harness log rarely says any of this directly. Claude Code's `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl` streams one content block per record, interleaves the results of parallel tool calls with the remaining blocks of the same response, injects skill bodies and reminders as user records, delivers prompts typed mid-turn as attachments, keeps rewound branches in the file, and marks the end of a turn only through a `turn_duration` record that older versions never wrote. Every future harness will have its own version of these gaps.

## Decision

Each source adapter owns the mapping from its log to the canonical form and reads the log in file order. `ClaudeSessionSource` merges the records sharing a `message.id` into one step regardless of what lies between them; treats a user record as human only when the harness says so (`origin.kind == "human"`, not meta, not a compaction summary) and also treats a `queued_command` attachment as human without starting a new turn; opens a new turn at a human prompt once the current turn has a step or an end; and derives `turn_end` from the `turn_duration` record (completed), a `[Request interrupted by user]` message (aborted), or a synthetic API-error message (error). When none of those appears, a turn whose last step stopped with `end_turn` is completed at the next prompt or the end of the log; a turn left at `tool_use` stays unended and is reported as interrupted. Synthetic assistant messages are never steps. Subagent transcripts under `<session-uuid>/subagents/` are not read. The domain never learns any of these record shapes.

## Alternatives considered

**Follow the `parentUuid` chain from the last leaf instead of file order.** That recovers exactly what the model saw at the end, but drops every branch the user rewound, and those branches are often the steps that drifted. File order keeps them; each rewound branch still begins with its human prompt, so its windows are well formed.

**Add a `claude` flavour to the domain (extra event kinds for attachments, thinking, or compaction).** The windows need none of it, and a domain that knows harness record shapes would make the next harness a domain change. The adapter drops what no probe reads.

**Treat every user record with text as a human message.** Skill bodies, compaction summaries, task notifications, and local-command output would then become `user_request` and the off-task probe would judge the assistant against text the user never wrote. The harness marks its own injections; the adapter trusts those marks.

**Leave old logs without turn ends.** Three of the author's sessions predate `turn_duration`; without the fallback every turn in them counts as interrupted and `goal.premature_stop` is never asked, for no reason a reader would accept. The `end_turn` stop reason is the model's own statement that it chose to stop.

## Consequences

A second harness converts with no change outside `adapters/` and `cli.py`, and the synthetic fixture for it documents each mapping rule as a test. The cost is that turn semantics differ slightly per harness (a queued prompt joins the running turn in Claude Code; dsh has no such message), so a cross-harness comparison of interrupted-turn counts is approximate. Subagent transcripts are a known gap; adding them is a `list_ids` change plus an id scheme that survives `<id>.jsonl` filenames.
