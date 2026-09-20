"""Reject credential-looking strings in tracked (default) or staged (--cached) files.

A line may carry the marker `hdd:allow-secret` when it intentionally holds a fake value; prefer
building fake secrets at runtime in tests instead.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW_MARKER = "hdd:allow-secret"
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("typesafe key", re.compile(r"apikey_[A-Za-z0-9_]{20,}")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".zst", ".zstd", ".lock", ".pyc"}


def listed_files(cached: bool) -> list[Path]:
    if cached:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    else:
        cmd = ["git", "ls-files"]
    out = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [ROOT / line for line in out.splitlines() if line]


def scan(path: Path) -> list[str]:
    if path.suffix in SKIP_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for label, pattern in PATTERNS:
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {label}")
    return hits


def main(argv: list[str]) -> int:
    cached = "--cached" in argv
    hits = [hit for path in listed_files(cached) for hit in scan(path)]
    for hit in hits:
        print(hit)
    if hits:
        print(
            f"verify-no-secrets: {len(hits)} credential-looking line(s); "
            "remove them or rotate the credential."
        )
        return 1
    print(f"verify-no-secrets: clean ({'staged' if cached else 'tracked'} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
