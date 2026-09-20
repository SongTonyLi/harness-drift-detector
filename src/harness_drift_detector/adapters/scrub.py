"""Text hygiene applied while converting harness logs.

Terminal output keeps ANSI escape sequences and transcripts occasionally quote a
credential; both are removed before a canonical transcript is written.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED_SECRET]"

_ANSI_RE = re.compile(
    r"""\x1b
    (?:
        \[ [0-?]* [ -/]* [@-~]          # CSI ... colours, cursor moves
      | \] [^\x07\x1b]* (?: \x07 | \x1b\\ )   # OSC ... terminated by BEL or ST
      | [@-Z\\-_]                       # two-character escapes
    )""",
    re.VERBOSE,
)

_BEARER_RE = re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]{20,}")

_SECRET_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bapikey_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (colours, cursor moves, OSC titles)."""
    return _ANSI_RE.sub("", text)


def scrub_secrets(text: str) -> str:
    """Replace credentials that match a known shape with REDACTED.

    `Bearer <token>` keeps the word `Bearer` so the shape of the header survives.
    """
    out = _BEARER_RE.sub(r"\g<1>" + REDACTED, text)
    for pattern in _SECRET_RES:
        out = pattern.sub(REDACTED, out)
    return out


def clean(text: str, scrub: bool = True) -> str:
    """Strip ANSI always; scrub secrets when asked."""
    out = strip_ansi(text)
    return scrub_secrets(out) if scrub else out
