"""Synthetic dsh v3 session logs.

Mirrors the shape of `~/.dsh/sessions/<encoded-cwd>/session-<uuid>/session.v3.jsonl`
without carrying any real transcript content.
"""

from __future__ import annotations

import json
from pathlib import Path

CWD = "/tmp/fixture-project"
CREATED_AT = 1789756882954
MODEL = "gpt-5.6-terra"
PROVIDER = "openai-codex"

# Obviously fake; assembled at import time so the literal never appears in a file.
# It matches the AWS access-key-id shape, which is what makes scrubbing observable.
FAKE_SECRET = "AKIA" + "0123456789ABCDEF"
ANSI_TOOL_TEXT = "\x1b[1ma.py\x1b[0m\nb.py\n[exit code: 0]"
ERROR_TOOL_TEXT = "rm: b.py: Permission denied\n[exit code: 1]\nAWS_KEY=" + FAKE_SECRET


def _line(**event: object) -> str:
    return json.dumps(event, ensure_ascii=False)


def _assistant(seq: int, turn: int, step: int, content: list[dict], stop_reason: str | None) -> str:
    source: dict[str, object] = {"kind": "model", "provider": PROVIDER, "model": MODEL}
    if stop_reason is not None:
        source["replayState"] = {"response": {"stopReason": stop_reason}, "blocks": []}
    return _line(
        type="assistant/message",
        seq=seq,
        time=CREATED_AT + seq,
        data={
            "turn": turn,
            "step": step,
            "message": {"role": "assistant", "content": content, "source": source},
        },
        surfaceOp="append",
    )


def _tool_result(
    seq: int, turn: int, step: int, call_id: str, text: str, is_error: bool | None
) -> str:
    block: dict[str, object] = {
        "type": "tool-result",
        "toolCallId": call_id,
        "content": [{"type": "text", "text": text}],
    }
    if is_error is not None:
        block["isError"] = is_error
    return _line(
        type="tool/result",
        seq=seq,
        time=CREATED_AT + seq,
        data={
            "turn": turn,
            "step": step,
            "message": {"source": {"kind": "tool", "callId": call_id}, "content": [block]},
        },
        surfaceOp="append",
    )


def build_session_lines(session_id: str = "session-fixture", two_turns: bool = True) -> list[str]:
    """One session: a human request, harness-injected messages, tool calls, an error."""
    lines = [
        _line(
            type="session",
            version=3,
            id=session_id,
            createdAt=CREATED_AT,
            cwd=CWD,
            isSeeded=False,
            delegationDepth=0,
        ),
        _line(type="permission/preset", seq=0, time=CREATED_AT, data={"preset": "workspace-write"}),
        _line(type="session/title", seq=1, time=CREATED_AT, data={"title": "fixture"}),
        _line(
            type="agent/inbox/spliced",
            seq=3,
            time=CREATED_AT,
            data={"target": "next-turn", "start": 0, "inserted": []},
        ),
        _line(type="turn/start", seq=4, time=CREATED_AT, data={"turn": 1}),
        _line(type="step/start", seq=6, time=CREATED_AT, data={"turn": 1, "step": 1}),
        _line(
            type="system/message",
            seq=7,
            time=CREATED_AT,
            data={
                "turn": 1,
                "step": 1,
                "message": {
                    "role": "system",
                    "content": [{"type": "text", "text": "You are a coding agent."}],
                },
            },
            surfaceOp="append",
        ),
        _line(
            type="user/message",
            seq=8,
            time=CREATED_AT,
            data={
                "content": [{"type": "text", "text": "list the files in the repo"}],
                "source": {"kind": "user"},
                "role": "user",
                "id": "msg-1",
            },
            surfaceOp="append",
        ),
        _line(
            type="user/message",
            seq=9,
            time=CREATED_AT,
            data={
                "content": [{"type": "text", "text": "Current runtime context: branch main."}],
                "source": {
                    "kind": "plugin",
                    "plugin": "@deepseek-ai/dsh-system-prompt",
                    "form": "snapshot",
                },
                "role": "user",
                "id": "msg-2",
            },
            surfaceOp="append",
        ),
        _line(
            type="user/message",
            seq=10,
            time=CREATED_AT,
            data={
                "content": [{"type": "text", "text": "<system-reminder>skills</system-reminder>"}],
                "source": {"kind": "skill-catalog", "form": "catalog"},
                "role": "user",
                "id": "msg-3",
            },
            surfaceOp="append",
        ),
        _line(
            type="request/header",
            seq=11,
            time=CREATED_AT,
            data={
                "header": {
                    "config": {"provider": PROVIDER, "model": MODEL, "maxTokens": 128000},
                    "tools": [],
                }
            },
        ),
        _line(
            type="request/context",
            seq=12,
            time=CREATED_AT,
            data={"provider": PROVIDER, "model": MODEL, "contextWindow": 272000},
        ),
        _assistant(
            15,
            1,
            1,
            [
                {"type": "reasoning", "text": ""},
                {"type": "text", "text": "I'll list them."},
                {
                    "type": "tool-call",
                    "id": "call_1|fc_1",
                    "name": "bash",
                    "arguments": '{"command":"ls"}',
                },
            ],
            "toolUse",
        ),
        _line(
            type="tool/call",
            seq=16,
            time=CREATED_AT,
            data={
                "turn": 1,
                "step": 1,
                "callId": "call_1|fc_1",
                "name": "bash",
                "arguments": '{"command":"ls"}',
            },
        ),
        _tool_result(17, 1, 1, "call_1|fc_1", ANSI_TOOL_TEXT, False),
        _line(type="step/end", seq=18, time=CREATED_AT, data={"turn": 1, "step": 1}),
        _line(type="step/start", seq=19, time=CREATED_AT, data={"turn": 1, "step": 2}),
        _assistant(20, 1, 2, [{"type": "text", "text": "There are two files."}], "stop"),
        _line(type="step/end", seq=21, time=CREATED_AT, data={"turn": 1, "step": 2}),
        _line(
            type="turn/end",
            seq=22,
            time=CREATED_AT,
            data={"turn": 1, "reason": {"kind": "completed"}},
        ),
    ]
    if not two_turns:
        return lines

    lines += [
        _line(type="turn/start", seq=23, time=CREATED_AT, data={"turn": 2}),
        _line(type="step/start", seq=24, time=CREATED_AT, data={"turn": 2, "step": 1}),
        _line(
            type="user/message",
            seq=25,
            time=CREATED_AT,
            data={
                "content": [{"type": "text", "text": "delete b.py"}],
                "source": {"kind": "user"},
                "role": "user",
                "id": "msg-4",
            },
            surfaceOp="append",
        ),
        _assistant(
            26,
            2,
            1,
            [
                {"type": "reasoning", "text": ""},
                {
                    "type": "tool-call",
                    "id": "call_2|fc_2",
                    "name": "bash",
                    "arguments": '{"command":"rm b.py"}',
                },
            ],
            "toolUse",
        ),
        _line(
            type="tool/call",
            seq=27,
            time=CREATED_AT,
            data={
                "turn": 2,
                "step": 1,
                "callId": "call_2|fc_2",
                "name": "bash",
                "arguments": '{"command":"rm b.py"}',
            },
        ),
        _tool_result(28, 2, 1, "call_2|fc_2", ERROR_TOOL_TEXT, True),
        _line(type="step/end", seq=29, time=CREATED_AT, data={"turn": 2, "step": 1}),
        _line(type="step/start", seq=30, time=CREATED_AT, data={"turn": 2, "step": 2}),
        _assistant(
            31,
            2,
            2,
            [
                {"type": "text", "text": "Done."},
                {
                    "type": "tool-call",
                    "id": "call_3|fc_3",
                    "name": "ask_user_question",
                    "arguments": '{"question":"Which file?"}',
                },
            ],
            None,
        ),
        _tool_result(32, 2, 2, "call_3|fc_3", "b.py", None),
        _line(type="step/end", seq=33, time=CREATED_AT, data={"turn": 2, "step": 2}),
        _line(
            type="turn/end",
            seq=34,
            time=CREATED_AT,
            data={"turn": 2, "reason": {"kind": "completed"}},
        ),
    ]
    return lines


def write_session_dir(
    root: Path,
    session_id: str = "session-fixture",
    compressed: bool = False,
    two_turns: bool = True,
) -> Path:
    """Write one session directory under `root`; returns the session directory."""
    directory = root / session_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session.lock").write_text("", encoding="utf-8")
    lines = build_session_lines(session_id, two_turns=two_turns)
    body = "".join(line + "\n" for line in lines)
    if not compressed:
        (directory / "session.v3.jsonl").write_text(body, encoding="utf-8")
        return directory

    import zstandard

    compressor = zstandard.ZstdCompressor()
    half = len(lines) // 2
    frames = [
        "".join(line + "\n" for line in lines[:half]),
        "".join(line + "\n" for line in lines[half:]),
    ]
    payload = b"".join(compressor.compress(frame.encode("utf-8")) for frame in frames)
    (directory / "session.v3.jsonl.zstd").write_bytes(payload)
    return directory
