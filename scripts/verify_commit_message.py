"""Reject commit messages that attribute the change to an assistant or code generator.

Usage: verify_commit_message.py <message-file>      (commit-msg hook)
       verify_commit_message.py --range <a>..<b>    (every commit in the range)
"""

from __future__ import annotations

import re
import subprocess
import sys

TOOL_NAMES = (
    r"(?:claude|anthropic|copilot|chatgpt|openai|gemini|codex|cursor|devin|aider|assistant"
    r"|\bai\b|llm|bot)"
)
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "assistant co-author trailer",
        re.compile(rf"^co-authored-by:.*{TOOL_NAMES}", re.IGNORECASE | re.MULTILINE),
    ),
    ("anthropic no-reply address", re.compile(r"noreply@anthropic\.com", re.IGNORECASE)),
    (
        "generated-with line",
        re.compile(rf"generated (?:with|by|using)\s+.*{TOOL_NAMES}", re.IGNORECASE),
    ),
    ("robot emoji", re.compile("\U0001f916")),
    (
        "assistant product name",
        re.compile(r"\bclaude (?:code|fable|opus|sonnet|haiku)\b", re.IGNORECASE),
    ),
    ("ai-generated label", re.compile(r"\bai[- ](?:generated|assisted|written)\b", re.IGNORECASE)),
)


def offenses(message: str) -> list[str]:
    return [label for label, pattern in PATTERNS if pattern.search(message)]


def commits_in(range_spec: str) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "log", "--format=%H%x00%B%x1e", range_spec],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commits = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        sha, _, body = record.strip("\n").partition("\x00")
        commits.append((sha.strip(), body))
    return commits


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--range":
        bad = [(sha[:10], found) for sha, body in commits_in(argv[1]) if (found := offenses(body))]
        for sha, found in bad:
            print(f"{sha}: {', '.join(found)}")
        if bad:
            print("verify-commit-message: commit messages must not carry tool attribution.")
            return 1
        print("verify-commit-message: clean.")
        return 0
    if len(argv) != 1:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        message = "".join(line for line in fh if not line.startswith("#"))
    found = offenses(message)
    if found:
        print(
            f"verify-commit-message: rejected ({', '.join(found)}). "
            "Describe the change and its reason; no tool attribution."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
