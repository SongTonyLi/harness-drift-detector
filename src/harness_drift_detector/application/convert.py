"""ConvertSessions: harness-native sessions -> canonical JSONL transcripts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.ports import TranscriptSource, TranscriptStore


@dataclass(frozen=True)
class ConvertSummary:
    converted: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (transcript id, reason)


class ConvertSessions:
    """One session at a time; a failure is recorded and never stops the batch."""

    def __init__(self, source: TranscriptSource, store: TranscriptStore) -> None:
        self.source = source
        self.store = store

    def run(self, out_dir: Path, ids: list[str] | None = None) -> ConvertSummary:
        out_dir = Path(out_dir)
        summary = ConvertSummary()
        for transcript_id in self.source.list_ids() if ids is None else ids:
            try:
                transcript = self.source.load(transcript_id)
                if not transcript.events:
                    summary.skipped.append((transcript_id, "no events"))
                    continue
                summary.converted.append(self.store.save(transcript, out_dir))
            except Exception as exc:  # one bad session must not abort the batch
                summary.skipped.append((transcript_id, f"{type(exc).__name__}: {exc}"))
        return summary
