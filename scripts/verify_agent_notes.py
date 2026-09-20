"""Check every Agent Note against .agents/notes/README.md: path encoding, header block,
status/lifecycle agreement, and the required section skeleton. Non-zero exit on any defect.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / ".agents" / "notes"
LIFECYCLES = ("proposed", "implemented", "rejected")
CLASSES = frozenset({"feature", "bug-fix", "simplification", "architecture", "process", "testing"})
FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
TITLE = re.compile(r"^# Agent Note: \S.*$")
STATUS_BY_LIFECYCLE = {
    "proposed": re.compile(r"^Status: proposed$"),
    "implemented": re.compile(r"^Status: implemented$"),
    "rejected": re.compile(r"^Status: rejected — \S.*$"),
}
REQUIRED_SECTIONS = {
    "proposed": [
        "## Problem",
        "## Proposal",
        "## Alternatives considered",
        "## Acceptance criteria",
        "## Risks",
    ],
    "implemented": ["## Problem", "## Decision", "## Alternatives considered", "## Consequences"],
    "rejected": ["## Problem", "## Proposal", "## Alternatives considered"],
}
FORBIDDEN_SECTIONS = {
    "implemented": ["## Proposal", "## Plan", "## Migration plan", "## Acceptance criteria"],
}


def check_note(path: Path, lifecycle: str) -> list[str]:
    problems: list[str] = []
    rel = path.relative_to(ROOT)
    if path.parent.name not in CLASSES:
        problems.append(f"{rel}: class folder {path.parent.name!r} is not one of {sorted(CLASSES)}")
    if not FILENAME.match(path.name):
        problems.append(f"{rel}: filename must be yyyy-mm-dd-topic-title.md")
    lines = path.read_text(encoding="utf-8").splitlines()
    if (
        len(lines) < 3
        or not TITLE.match(lines[0])
        or lines[1] != ""
        or not STATUS_BY_LIFECYCLE[lifecycle].match(lines[2])
    ):
        problems.append(
            f"{rel}: header must be '# Agent Note: <title>', a blank line, "
            f"then a {lifecycle} Status line"
        )
    headings = [line for line in lines if line.startswith("## ")]
    if not headings or headings[0] != "## Problem":
        problems.append(f"{rel}: the first H2 must be '## Problem'")
    for section in REQUIRED_SECTIONS[lifecycle]:
        if section not in headings:
            problems.append(f"{rel}: missing required section {section!r}")
    for section in FORBIDDEN_SECTIONS.get(lifecycle, []):
        if section in headings:
            problems.append(f"{rel}: {section!r} may not appear in an implemented note")
    if lines and lines[-1].strip() == "":
        problems.append(f"{rel}: trailing blank line; end with exactly one newline")
    return problems


def main() -> int:
    problems: list[str] = []
    count = 0
    for lifecycle in LIFECYCLES:
        folder = NOTES / lifecycle
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.md")):
            count += 1
            problems.extend(check_note(path, lifecycle))
    for path in NOTES.rglob("*.md"):
        if path.relative_to(NOTES).parts[0] not in LIFECYCLES and path.name != "README.md":
            problems.append(
                f"{path.relative_to(ROOT)}: notes live under proposed/, implemented/, or rejected/"
            )
    for problem in problems:
        print(problem)
    if problems:
        print(f"verify-agent-notes: {len(problems)} problem(s) in {count} note(s).")
        return 1
    print(f"verify-agent-notes: {count} note(s) conform.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
