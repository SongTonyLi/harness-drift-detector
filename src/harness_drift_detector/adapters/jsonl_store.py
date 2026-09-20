"""Canonical JSONL transcripts on disk.

One file per transcript: the header line first, then one line per event in seq order.
The record mapping itself lives in the domain; this adapter only does the I/O.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from ..domain.transcript import (
    Event,
    Transcript,
    event_to_record,
    header_to_record,
    record_to_event,
    record_to_header,
)


class JsonlTranscriptStore:
    """TranscriptStore over `<directory>/<transcript_id>.jsonl` files."""

    def save(self, transcript: Transcript, directory: Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{transcript.transcript_id}.jsonl"
        records = [header_to_record(transcript.header)]
        records.extend(event_to_record(event) for event in transcript.events)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def load(self, path: Path) -> Transcript:
        path = Path(path)
        header = None
        events: list[Event] = []
        with path.open("r", encoding="utf-8") as handle:
            for lineno, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}: line {lineno} is not valid JSON: {exc.msg}") from exc
                if header is None:
                    if record.get("kind") != "transcript":
                        raise ValueError(f"{path}: line {lineno} is not a transcript header")
                    header = record_to_header(record)
                    continue
                events.append(record_to_event(record))
        if header is None:
            raise ValueError(f"{path}: no transcript header")
        return Transcript(header=header, events=tuple(events))

    def load_many(self, paths: Iterable[Path]) -> list[Transcript]:
        return [self.load(path) for path in paths]
