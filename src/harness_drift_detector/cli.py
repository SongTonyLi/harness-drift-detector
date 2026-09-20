"""`hdd`: convert harness sessions, detect drift, list hotspots.

Adapters are imported inside the command functions so that importing this module (and
running `hdd --help`) never needs an SDK, a key, or a network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .application.detect import DetectDrift, DetectOptions
from .application.render import render_hotspots, render_json, render_markdown, render_terminal
from .domain.policy import DriftPolicy
from .domain.probes import CATALOG
from .domain.transcript import Transcript

DEFAULT_MODEL = "jev-latest"
DEFAULT_REPORTS_DIR = Path("reports")
DEFAULT_CACHE_DIR = Path(".hdd-cache")


def _positive_int(value: str) -> int:
    """argparse type: a count that must be at least 1 (0 would stall, negatives crash)."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {number}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdd", description="Drift hotspotting for harness transcripts"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="convert harness sessions to canonical JSONL")
    convert.add_argument("--harness", default="dsh", choices=["dsh"])
    convert.add_argument(
        "--root", required=True, type=Path, help="directory holding session-<uuid> dirs"
    )
    convert.add_argument(
        "--out", required=True, type=Path, help="output directory for .jsonl transcripts"
    )
    convert.add_argument("--ids", nargs="+", default=None, help="only these session ids")
    convert.add_argument("--no-scrub", action="store_true", help="do not scrub secrets")
    convert.set_defaults(func=cmd_convert)

    detect = sub.add_parser("detect", help="judge every assistant step of one or more transcripts")
    detect.add_argument("paths", nargs="+", type=Path)
    detect.add_argument(
        "--judge",
        required=True,
        choices=["typesafe", "heuristic"],
        help="typesafe: the calibrated System One judge. heuristic: an offline lexical "
        "baseline whose scores are not calibrated probabilities",
    )
    detect.add_argument("--model", default=DEFAULT_MODEL)
    detect.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR)
    detect.add_argument("--threshold", type=float, default=DriftPolicy().fire_threshold)
    detect.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="PROBE=THRESHOLD",
        help="firing threshold for one probe, e.g. tool.unsupported_claim=0.9; repeatable",
    )
    detect.add_argument("--concurrency", type=_positive_int, default=DetectOptions().concurrency)
    detect.add_argument("--probes", default=None, help="comma-separated probe ids to ask")
    detect.add_argument("--no-cache", action="store_true")
    detect.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    detect.set_defaults(func=cmd_detect)

    hotspots = sub.add_parser("hotspots", help="print the ranked hotspots of a saved JSON report")
    hotspots.add_argument("report", type=Path)
    hotspots.add_argument("--top", type=_positive_int, default=None)
    hotspots.set_defaults(func=cmd_hotspots)

    return parser


def cmd_convert(args: argparse.Namespace) -> int:
    from .adapters.dsh_source import DshSessionSource
    from .adapters.jsonl_store import JsonlTranscriptStore
    from .application.convert import ConvertSessions

    source = DshSessionSource(args.root, scrub=not args.no_scrub)
    summary = ConvertSessions(source, JsonlTranscriptStore()).run(args.out, args.ids)
    for path in summary.converted:
        print(path)
    for transcript_id, reason in summary.skipped:
        print(f"skipped {transcript_id}: {reason}", file=sys.stderr)
    print(f"converted {len(summary.converted)}, skipped {len(summary.skipped)}", file=sys.stderr)
    return 0


def _load_transcripts(paths: Sequence[Path]) -> list[Transcript]:
    from .adapters.jsonl_store import JsonlTranscriptStore

    store = JsonlTranscriptStore()
    transcripts = []
    for path in paths:
        try:
            transcripts.append(store.load(path))
        except Exception as exc:  # one unreadable file never aborts the batch
            print(f"skipped {path}: {exc}", file=sys.stderr)
    return transcripts


def _build_judge(args: argparse.Namespace):
    if args.judge == "typesafe":
        from .adapters.typesafe_judge import TypeSafeJudge

        judge = TypeSafeJudge(model=args.model)
    else:
        from .adapters.heuristic_judge import HeuristicJudge

        judge = HeuristicJudge()

    if args.no_cache:
        return judge

    from .adapters.caching_judge import CachingJudge, FileJudgmentCache

    return CachingJudge(judge, FileJudgmentCache(args.cache_dir))


async def _detect(judge, transcripts: list[Transcript], options: DetectOptions):
    try:
        return await DetectDrift(judge, options).run_many(transcripts)
    finally:
        aclose = getattr(judge, "aclose", None)
        if aclose is not None:
            await aclose()


def _parse_probe_ids(raw: str | None) -> set[str] | None:
    """None when --probes was not given. Unknown ids raise: a typo must not silently judge
    nothing and report a clean session."""
    if not raw:
        return None
    wanted = {part.strip() for part in raw.split(",") if part.strip()}
    unknown = sorted(wanted - set(CATALOG))
    if unknown:
        raise ValueError(
            f"unknown probe id(s): {', '.join(unknown)}; known ids: {', '.join(CATALOG)}"
        )
    return wanted


def _parse_overrides(raw: Sequence[str]) -> dict[str, float]:
    """`PROBE=THRESHOLD` pairs; unknown ids and thresholds outside [0, 1] raise."""
    overrides: dict[str, float] = {}
    for item in raw:
        probe_id, sep, value = item.partition("=")
        probe_id = probe_id.strip()
        if not sep or probe_id not in CATALOG:
            raise ValueError(
                f"bad --override {item!r}: expected PROBE=THRESHOLD with a known probe id; "
                f"known ids: {', '.join(CATALOG)}"
            )
        try:
            threshold = float(value)
        except ValueError:
            raise ValueError(f"bad --override {item!r}: threshold must be a number") from None
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"bad --override {item!r}: threshold must be between 0 and 1")
        overrides[probe_id] = threshold
    return overrides


def cmd_detect(args: argparse.Namespace) -> int:
    if args.judge == "typesafe" and not os.environ.get("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set", file=sys.stderr)
        return 2

    try:
        only_probes = _parse_probe_ids(args.probes)
        overrides = _parse_overrides(args.override)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    transcripts = _load_transcripts(args.paths)
    if not transcripts:
        print("no transcripts to judge", file=sys.stderr)
        return 1

    options = DetectOptions(
        policy=DriftPolicy(fire_threshold=args.threshold, overrides=overrides),
        concurrency=args.concurrency,
        only_probes=only_probes,
    )
    reports = asyncio.run(_detect(_build_judge(args), transcripts, options))

    args.out.mkdir(parents=True, exist_ok=True)
    for report in reports:
        (args.out / f"{report.transcript_id}.json").write_text(
            render_json(report), encoding="utf-8"
        )
        (args.out / f"{report.transcript_id}.md").write_text(
            render_markdown(report), encoding="utf-8"
        )
        print(render_terminal(report))
    return 0


def cmd_hotspots(args: argparse.Namespace) -> int:
    try:
        data = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {args.report}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict) or "hotspots" not in data:
        print(f"{args.report} is not a drift report", file=sys.stderr)
        return 2
    print(render_hotspots(data, top=args.top))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
