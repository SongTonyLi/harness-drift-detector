# Agent Notes

An **Agent Note** records a decision or proposal that affects this codebase: the why and what was given up, which code and docs cannot carry. This file defines where notes live, when to write one, and the in-file format that `scripts/verify_agent_notes.py` enforces.

## Layout and naming

Path encodes two axes: `{lifecycle}/{class}/yyyy-mm-dd-topic-title.md`.

- **Lifecycle** (top folder) is the note's status and the note moves as it changes: `proposed/` (reviewed before implementation), `implemented/` (shipped; kept current with what actually shipped, facts only), `rejected/` (considered and declined; kept only while it prevents a tempting mistake).
- **Class** (nested folder) is the kind of decision, from a closed set: `feature`, `bug-fix`, `simplification`, `architecture` (structure of the shipped source), `process` (tooling, policy, and workflow around the code), `testing`.

The date is when the topic was first proposed. Cross-references between notes use relative markdown links so they survive moves. There is no index file; browse the tree or search.

## When to write one

Add or update a note in the same change only for lasting decision rationale that code, tests, and existing documentation do not explain. A proposal for substantial future work starts in `proposed/`; a decision already made starts in `implemented/`. Updating the note that already owns a decision satisfies the rule; never edit a note into a different decision, supersede it with a new one and cross-link both. Mechanical or local edits are exempt.

## The file format

The first three lines are exactly:

```markdown
# Agent Note: <title>

Status: <status>
```

followed by a blank line. `Status:` is one of `Status: proposed`, `Status: implemented`, or `Status: rejected — <why, in one line>` and must agree with the lifecycle folder.

The body opens with `## Problem`, written to stand without the solution. Then, by lifecycle:

- `proposed/`: `## Proposal`, bespoke sections, `## Alternatives considered`, `## Acceptance criteria`, `## Risks`.
- `implemented/`: `## Decision` (present tense, shipped reality), bespoke sections, `## Alternatives considered`, `## Consequences` (what the trade-off cost and bought). `## Proposal`, `## Plan`, `## Migration plan`, and `## Acceptance criteria` may not appear.
- `rejected/`: the frozen proposal with `## Proposal` and `## Alternatives considered`; the verdict lives on the `Status:` line.

`## Alternatives considered` is mandatory everywhere: each genuine alternative and why it lost, one bold-led paragraph per alternative. A decision recorded without what it beat invites re-litigation.

Moving between lifecycles means updating `Status:` and re-satisfying the target skeleton in the same change.
