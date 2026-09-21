"""Synthetic Claude Code session logs.

Mirrors the shape of `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl` without
carrying any real transcript content: a streamed response with interleaved parallel tool
results, a queued prompt, an interruption, harness-injected user records, a synthetic
assistant message, an API error, and turns that end without a `turn_duration` record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.dsh_v3 import ANSI_TOOL_TEXT, ERROR_TOOL_TEXT, FAKE_SECRET

SESSION_ID = "0f0f0f0f-0000-4000-8000-000000000001"
CWD = "/tmp/fixture-project"
MODEL = "claude-fable-5-1"
FIRST_TIMESTAMP = "2026-09-14T01:41:55.972Z"
CREATED_AT = 1789350115972  # FIRST_TIMESTAMP in epoch milliseconds

SKILL_BODY = "Base directory for this skill: /tmp/skills/tdd\n\n# Test-Driven Development"
COMPACT_SUMMARY = "This session is being continued from a previous conversation. Summary: ..."
TASK_NOTIFICATION = (
    "<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>\n</task-notification>"
)
SLASH_COMMAND = (
    "<command-message>herdr</command-message>\n<command-name>/herdr</command-name>\n"
    "<command-args>watch tab 5</command-args>"
)
LOCAL_COMMAND = (
    "<command-name>/model</command-name>\n            <command-message>model</command-message>"
    "\n            <command-args>fable</command-args>"
)
LOCAL_STDOUT = "<local-command-stdout>Set model to `Fable 5.1`</local-command-stdout>"

__all__ = [
    "ANSI_TOOL_TEXT",
    "CREATED_AT",
    "CWD",
    "ERROR_TOOL_TEXT",
    "FAKE_SECRET",
    "MODEL",
    "SESSION_ID",
    "build_session_lines",
    "write_session_file",
]


def _line(**record: Any) -> str:
    return json.dumps(record, ensure_ascii=False)


def _envelope(record_type: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "parentUuid": None,
        "isSidechain": False,
        "type": record_type,
        "uuid": f"uuid-{record_type}",
        "timestamp": FIRST_TIMESTAMP,
        "userType": "external",
        "entrypoint": "cli",
        "cwd": CWD,
        "sessionId": SESSION_ID,
        "version": "2.1.260",
        "gitBranch": "main",
    }
    base.update(extra)
    return base


def _human(text: str, prompt_source: str = "typed") -> str:
    return _line(
        **_envelope(
            "user",
            message={"role": "user", "content": text},
            origin={"kind": "human"},
            promptSource=prompt_source,
        )
    )


def _harness_user(content: Any, **flags: Any) -> str:
    return _line(**_envelope("user", message={"role": "user", "content": content}, **flags))


def _tool_result(call_id: str, content: Any, is_error: bool | None = None) -> str:
    block: dict[str, Any] = {"tool_use_id": call_id, "type": "tool_result", "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    return _line(
        **_envelope(
            "user", message={"role": "user", "content": [block]}, toolUseResult={"ok": True}
        )
    )


def _assistant(
    message_id: str,
    block: dict[str, Any],
    stop_reason: str | None = "tool_use",
    model: str = MODEL,
    sidechain: bool = False,
) -> str:
    return _line(
        **_envelope(
            "assistant",
            isSidechain=sidechain,
            requestId=f"req-{message_id}",
            apiBlockIndex=0,
            message={
                "model": model,
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "content": [block],
                "stop_reason": stop_reason,
                "usage": {"input_tokens": 2, "output_tokens": 7},
            },
        )
    )


def _tool_use(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _system(subtype: str, **extra: Any) -> str:
    return _line(**_envelope("system", subtype=subtype, **extra))


def _attachment(attachment: dict[str, Any]) -> str:
    return _line(**_envelope("attachment", attachment=attachment))


def build_session_lines(session_id: str = SESSION_ID) -> list[str]:
    """Five turns: completed, interrupted, ended by an API error, and two that end without a
    `turn_duration` record (at the next prompt and at the end of the log)."""
    del session_id  # the id lives in the file name; records carry SESSION_ID
    return [
        # -- turn 1: completed
        _line(type="last-prompt", leafUuid=None, sessionId=SESSION_ID),
        _attachment({"type": "hook_success", "hookName": "SessionStart", "stdout": "ok"}),
        _human("list the files in the repo"),
        _harness_user([_text(SKILL_BODY)], isMeta=True),
        _assistant("msg_A", {"type": "thinking", "thinking": "", "signature": "sig"}, None),
        _assistant("msg_A", _text("I'll list them.")),
        _assistant("msg_A", _tool_use("toolu_1", "Bash", {"command": "ls"})),
        _tool_result("toolu_1", ANSI_TOOL_TEXT, is_error=False),
        _assistant("msg_B", _tool_use("toolu_2", "Read", {"file_path": "a.py"})),
        _tool_result("toolu_2", "print('a')", is_error=False),
        _harness_user([_text("Only you see that command's output.")]),
        _assistant("msg_B", _tool_use("toolu_3", "Read", {"file_path": "b.py"})),
        _tool_result(
            "toolu_3",
            [_text("print('b')"), {"type": "image", "source": {"type": "base64", "data": "x"}}],
        ),
        _assistant("msg_C", _text("There are two files."), stop_reason="end_turn"),
        _system("stop_hook_summary", hookCount=1, hookErrors=[]),
        _system("turn_duration", durationMs=1200, messageCount=9),
        _line(type="queue-operation", operation="enqueue", sessionId=SESSION_ID, content="x"),
        # -- turn 2: a queued prompt mid-turn, then the user interrupts a tool call
        _human("delete b.py"),
        _assistant("msg_D", _text("Deleting.")),
        _assistant("msg_D", _tool_use("toolu_4", "Bash", {"command": "rm b.py"})),
        _attachment(
            {
                "type": "queued_command",
                "prompt": "and a.py too",
                "commandMode": "prompt",
                "origin": {"kind": "human"},
            }
        ),
        # the same queue carries the harness's own deliveries; neither is a new request
        _attachment(
            {
                "type": "queued_command",
                "prompt": TASK_NOTIFICATION,
                "commandMode": "task-notification",
            }
        ),
        _attachment(
            {
                "type": "queued_command",
                "prompt": "Goal set: finish the cleanup",
                "commandMode": "prompt",
                "origin": {"kind": "auto-continuation"},
            }
        ),
        _tool_result("toolu_4", ERROR_TOOL_TEXT, is_error=True),
        _harness_user([_text("[Request interrupted by user for tool use]")]),
        _assistant(
            "synthetic-1",
            _text("No response requested."),
            stop_reason="stop_sequence",
            model="<synthetic>",
        ),
        # -- turn 3: a skill invocation, local commands, injected context, an API error
        _human(SLASH_COMMAND, prompt_source="typed"),
        _harness_user([_text(SKILL_BODY)], isMeta=True),
        _harness_user(LOCAL_COMMAND),
        _harness_user(LOCAL_STDOUT),
        _harness_user(COMPACT_SUMMARY, isCompactSummary=True, isVisibleInTranscriptOnly=True),
        _harness_user(
            TASK_NOTIFICATION, origin={"kind": "task-notification"}, promptSource="system"
        ),
        _assistant("side-1", _text("I am a subagent."), stop_reason="end_turn", sidechain=True),
        _assistant(
            "msg_E", {"type": "thinking", "thinking": "", "signature": "sig"}, stop_reason=None
        ),
        _assistant("msg_E", _text("Watching."), stop_reason=None),
        _assistant(
            "synthetic-2",
            _text("API Error: Connection lost mid-response. The response above may be incomplete."),
            stop_reason="stop_sequence",
            model="<synthetic>",
        ),
        # -- turns 4 and 5: no turn_duration records, as older versions wrote them
        _human("thanks"),
        _assistant("msg_F", _text("Done."), stop_reason="end_turn"),
        _human("one more"),
        _assistant("msg_G", _text("Sure."), stop_reason="end_turn"),
        _line(type="cost-state", sessionId=SESSION_ID, totalCostUSD=0.5),
    ]


def write_session_file(root: Path, session_id: str = SESSION_ID) -> Path:
    """Write `<root>/<session_id>.jsonl` plus the sibling directories a real project
    directory carries (a subagent transcript and the memory folder); returns the log path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session_id}.jsonl"
    path.write_text("".join(line + "\n" for line in build_session_lines(session_id)), "utf-8")
    subagents = root / session_id / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / "agent-a1.jsonl").write_text(build_session_lines()[2] + "\n", "utf-8")
    (root / "memory").mkdir(exist_ok=True)
    (root / "memory" / "MEMORY.md").write_text("", "utf-8")
    return path
