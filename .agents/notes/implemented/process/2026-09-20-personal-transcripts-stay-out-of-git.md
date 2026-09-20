# Agent Note: Personal transcripts and credentials stay out of git

Status: implemented

## Problem

The detector is validated on the author's real harness sessions, which contain private prompts, local paths, tool output, and can contain credentials pasted into a terminal. The repository is public. Test fixtures still need realistic session logs.

## Decision

Converted transcripts, reports, and the judgment cache live under `data/`, `reports/`, and `.hdd-cache/`, all gitignored. Tests build synthetic sessions with `tests/fixtures/dsh_v3.py` instead of reading real logs. The converter's `adapters/scrub.py` removes ANSI sequences and replaces credential patterns with `[REDACTED_SECRET]` before a transcript is written. `scripts/verify_no_secrets.py` rejects credential patterns in staged files at commit and in tracked files at push and in CI; a line may carry `hdd:allow-secret` only for an intentional fake value. `TYPESAFE_API_KEY` is read from the environment only. README validation figures are counts and timings, never transcript text.

## Alternatives considered

**Commit a redacted copy of the real sessions as fixtures.** Realistic, but redaction of prose is judgment work that can miss, and the sessions would still expose working habits and paths. Synthetic fixtures cover the format exhaustively with no exposure.

**Rely on `.gitignore` alone.** Stops the common case but not a pasted key in a test or README. The scan runs on staged content so the mistake is caught before a commit exists.

**Scan only in CI.** Too late: the secret is already in a pushed commit and must be rotated. Local hooks catch it first; CI is the backstop.

## Consequences

Contributors can run every test with no private data. A real key that leaks into a file fails the commit locally. The cost is maintaining the fixture builder alongside the converter and remembering that the scan matches patterns, not intent: rotate any credential the gate reports.
