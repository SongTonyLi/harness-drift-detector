# Agent Note: Mechanical gates over prose guidelines

Status: implemented

## Problem

This repository is developed mostly by coding agents working from `AGENTS.md`. Agents follow enforced checks far more reliably than prose, and a rule that lives only in prose drifts with every agent turnover. The rules that matter here are mechanically checkable: the layer dependency rule, the Agent Note format, absence of credentials, formatting, tests, and git-message hygiene.

## Decision

Every checkable promise in `AGENTS.md` has a script under `scripts/` that exits non-zero: `verify_layering.py`, `verify_agent_notes.py`, `verify_no_secrets.py`, `verify_commit_message.py`, plus `ruff` and `pytest`. `scripts/gates.py` runs a named set with bounded concurrency and attributable output; `pre-push` is what the git hook runs and `ci` adds the package build. lefthook wires the hooks: pre-commit fixes staged formatting, checks staged whitespace, and scans staged files for credentials; commit-msg checks attribution; pre-push runs the `pre-push` gates. CI runs `gates.py ci` and the commit-message range check on pull requests. A new rule lands with its gate in the same change.

## Alternatives considered

**pre-commit framework instead of lefthook.** Widely used in Python, but its hooks are per-file wrappers around external repos; lefthook runs plain commands in parallel with no hook registry, matches the pattern already used across the maintainer's other repositories, and installs from PyPI.

**Run every gate on pre-commit.** Slower commits discourage small commits; the test suite belongs at push time, where the hook still costs seconds because the suite is small and offline.

**CI only.** Leaves the fast local signal on the table and lets a bad commit exist before anything objects.

## Consequences

Conventions survive agent turnover and are visible as failing commands rather than review comments. The gates are code to maintain and their inventory must stay in `gates.py`, not duplicated in workflow YAML. A contributor must run `uv run lefthook install` once per clone; CI catches anyone who did not.
