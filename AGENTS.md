# AGENTS.md

harness-drift-detector (`hdd`) converts coding-agent harness sessions into canonical JSONL transcripts, scores every assistant step on alignment dimensions with a System One judge, and ranks drift hotspots. Read [docs/architecture.md](docs/architecture.md) before changing `src/`; durable decisions live in [Agent Notes](.agents/notes/README.md).

## Repository layout

```
src/harness_drift_detector/
  domain/        pure model: transcript, windows, probe catalog, judgments, policy, report, ports
  application/   use cases: convert, detect, render
  adapters/      dsh and Claude Code session sources, JSONL store, judges (typesafe, heuristic, caching, fake), scrubbing
  cli.py         `hdd convert | detect | hotspots`
tests/           mirrors src/; tests/fixtures/{dsh_v3,claude_code}.py build synthetic harness sessions
scripts/         gates; scripts/gates.py runs them
.agents/         notes/ (decision records) and skills/ (agent procedures)
docs/            architecture, design specs, implementation plans
data/ reports/ .hdd-cache/   local only, gitignored
```

## Commands

```sh
uv sync                                    # install (Python >= 3.12)
uv run lefthook install                    # git hooks, once per clone
uv run pytest -q                           # unit + integration tests, no network
uv run pytest -m live -q                   # real TypeSafe calls; skipped without TYPESAFE_API_KEY
uv run ruff check . && uv run ruff format --check .
uv run python scripts/gates.py pre-push    # what the pre-push hook runs
uv run python scripts/gates.py ci          # everything CI runs
uv run hdd convert --harness dsh --root ~/.dsh/sessions/<encoded-cwd> --out data/transcripts
uv run hdd convert --harness claude --root ~/.claude/projects/<encoded-cwd> --out data/transcripts
uv run hdd detect data/transcripts/*.jsonl --judge typesafe --out reports
uv run hdd hotspots reports/<transcript-id>.json --top 10
```

## Run relevant checks locally

Before pushing, follow [hdd-pre-push-checks](.agents/skills/hdd-pre-push-checks/SKILL.md): run the narrowest tests that would fail for the diff's regression, then let the pre-push hook run the gates once. Report only commands you actually ran. When reviewing, use [hdd-code-review](.agents/skills/hdd-code-review/SKILL.md).

## Secrets

`TYPESAFE_API_KEY` is read from the environment only. Never write a key into a tracked file, fixture, log, report, or message; `scripts/verify_no_secrets.py` rejects credential patterns in staged and tracked files, and the converter scrubs them from transcripts ([decision](.agents/notes/implemented/process/2026-09-20-personal-transcripts-stay-out-of-git.md)).

## Git messages

Commit messages and PR bodies name the change and its reason. They carry no tool attribution: no `Co-Authored-By` trailer for an assistant, no "generated with" line, no assistant product names ([decision](.agents/notes/implemented/process/2026-09-20-no-tool-attribution-in-git-messages.md)). `scripts/verify_commit_message.py` rejects them in the commit-msg hook and in CI.

## Conventions

- **Dependency rule.** `domain/` imports the standard library and other `domain/` modules only; `application/` adds `domain/`; `adapters/` implement `domain/ports.py` and the `Judge` protocol in `domain/judgment.py`; `cli.py` wires adapters into use cases. `typesafe_sdk` is imported only by `adapters/typesafe_judge.py`. `scripts/verify_layering.py` enforces this ([decision](.agents/notes/implemented/architecture/2026-09-20-judge-port-with-typesafe-as-one-provider.md)).
- **TypeSafe is one provider.** A new judge is an adapter implementing `Judge` plus a `--judge` choice in `cli.py`; the domain never learns provider names. Follow [hdd-add-judge-provider](.agents/skills/hdd-add-judge-provider/SKILL.md).
- **Probes are narrow and `true` means drift.** Every Noul in `domain/probes.py` states `true_criteria` and `false_criteria` aligned with its instructions, names the state fields it reads in backticks, and has a precondition so unasked probes never reach a request. The gate is max-style over Nouls, never a mean; Scores rank hotspots and never fire one ([decision](.agents/notes/implemented/architecture/2026-09-20-drift-probes-follow-the-sde-cascade.md)).
- **Thresholds live in code.** `DriftPolicy` applies after judging; changing a threshold never reruns inference because the cache key covers model, state, and probes only.
- **Small state.** A window carries only the fields probes reference; `Budget` truncates with an explicit omitted-chars marker. Do not add the system prompt or unrelated turns to a window.
- **Canonical JSONL is a contract.** Header line first, one event per line, `kind` as the first key. A format change updates `domain/transcript.py`, `docs/architecture.md`, and both fixtures in `tests/fixtures/` in the same change. A harness source is an adapter implementing `TranscriptSource` plus a `--harness` choice in `cli.py`; it reads its log in file order and maps turn ends itself ([decision](.agents/notes/implemented/architecture/2026-09-20-harness-sources-map-turns-in-file-order.md)).
- **Personal transcripts stay out of git.** Tests use the synthetic fixture; README validation numbers are counts only.
- **Tests describe behavior.** Domain tests use hand-built transcripts; adapters get a fake client or `FakeJudge`; `live` tests are opt-in and skip without a key.
- **Agent Notes** record durable rationale only ([when to write one](.agents/notes/README.md#when-to-write-one)); `scripts/verify_agent_notes.py` checks the format.
- **Mechanical over prose.** Every checkable rule here has a script that exits non-zero ([decision](.agents/notes/implemented/process/2026-09-20-mechanical-gates-over-prose-guidelines.md)). Add the gate with the rule.
- Files end with exactly one trailing newline; `git diff --cached --check` gates whitespace at commit.

## Editing these instructions

`CLAUDE.md` symlinks `AGENTS.md`; edit the real file. Keep each rule to one to three lines that link its home.
