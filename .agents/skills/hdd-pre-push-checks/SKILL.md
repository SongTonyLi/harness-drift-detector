---
name: hdd-pre-push-checks
description: Use before pushing, opening a pull request, or claiming checks pass on a harness-drift-detector branch, to select the narrowest tests and checks that cover the outgoing diff and to run the gates once, without reflexively rerunning everything.
---

# HDD Pre-Push Checks

Run relevant local evidence once before a push. The git hooks are deliberately narrow: pre-commit fixes staged formatting, checks staged whitespace, and scans staged files for credentials; commit-msg rejects tool attribution; pre-push runs `scripts/gates.py pre-push` (layering, agent-note format, secret scan, ruff, offline tests). CI runs the same gates plus the package build and the commit-message range check.

## Inspect the outgoing change

```sh
git status --short --branch
git diff --stat origin/main...HEAD
```

If the branch has no upstream yet, diff against `origin/main`.

## Select the evidence for the diff

Every behavior change needs the narrowest test that would fail for its regression. Map changed paths to owning tests:

| Changed path | Run |
| --- | --- |
| `domain/transcript.py` | `uv run pytest tests/domain/test_transcript.py tests/adapters/test_jsonl_store.py -q` |
| `domain/window.py` | `uv run pytest tests/domain/test_window.py tests/domain/test_probes.py tests/application/test_detect.py -q` |
| `domain/probes.py` | `uv run pytest tests/domain/test_probes.py -q`; if wording changed, also the live spot check below |
| `domain/policy.py`, `domain/report.py` | `uv run pytest tests/domain/test_policy.py tests/domain/test_report.py tests/application/test_render.py -q` |
| `adapters/dsh_source.py`, `adapters/scrub.py`, `application/convert.py` | `uv run pytest tests/adapters/test_dsh_source.py tests/adapters/test_scrub.py tests/application/test_convert.py -q` |
| `adapters/*_judge.py`, `adapters/caching_judge.py` | the adapter's test plus `uv run pytest tests/application/test_detect.py -q` |
| `application/detect.py`, `application/render.py`, `cli.py` | `uv run pytest tests/application tests/test_cli.py -q` |
| `scripts/*.py`, `lefthook.yml`, `.github/` | `uv run python scripts/gates.py pre-push` and read the output |
| `.agents/notes/**` | `uv run python scripts/verify_agent_notes.py` |
| `README.md`, `docs/` | `uv run hdd --help` and each subcommand's `--help`; confirm every documented flag exists |

Do not repeat a passing check merely because commit or push follows; the pre-push hook runs the gates once.

### Live spot check for probe wording

Changing a probe's instructions or criteria changes the cache key, so a detect run reruns inference for that probe. With the key in the environment:

```sh
uv run pytest -m live -q
uv run hdd detect data/transcripts/*.jsonl --judge typesafe --out reports
```

Compare hotspot counts and the top hotspots against the previous report before and after the wording change. Never paste transcript text or the key into the PR.

## Handle failures

If a relevant check fails, stop and fix or explain the blocker. Do not push and hope CI differs. Bypass a hook (`LEFTHOOK=0`) only when the user explicitly asks, and report exactly what failed.

## Push procedure

1. Run the selected checks once.
2. Commit normally; inspect any files the pre-commit fixer changed.
3. Push normally so the pre-push gates run.
4. Verify the remote matches local: `git rev-parse HEAD origin/$(git branch --show-current)`.
5. For a PR: `gh pr checks`; report pending checks as pending.
