import pytest

from harness_drift_detector.adapters.claude_source import (
    ClaudeSessionSource,
    normalize_command,
    parse_claude_lines,
)
from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    ToolResultEvent,
    TurnEndEvent,
    UserEvent,
)
from tests.fixtures.claude_code import (
    CREATED_AT,
    CWD,
    FAKE_SECRET,
    MODEL,
    SESSION_ID,
    build_session_lines,
    write_session_file,
)

SOURCE = f"/fixture/{SESSION_ID}.jsonl"


def _parse(**kwargs):
    return parse_claude_lines(build_session_lines(), SOURCE, **kwargs)


def test_header_takes_id_from_the_file_and_model_from_the_first_real_response():
    header = _parse().header
    assert header.transcript_id == SESSION_ID
    assert header.harness == "claude"
    assert header.source_path == SOURCE
    assert (header.model, header.provider) == (MODEL, None)
    assert (header.cwd, header.created_at) == (CWD, CREATED_AT)


def test_event_kinds_and_turns_in_file_order():
    events = _parse().events
    assert [(e.kind, e.turn) for e in events] == [
        ("user", 1),
        ("user", 1),
        ("assistant", 1),
        ("tool_result", 1),
        ("assistant", 1),
        ("tool_result", 1),
        ("user", 1),
        ("tool_result", 1),
        ("assistant", 1),
        ("turn_end", 1),
        ("user", 2),
        ("assistant", 2),
        ("user", 2),
        ("user", 2),
        ("user", 2),
        ("tool_result", 2),
        ("turn_end", 2),
        ("user", 3),
        ("user", 3),
        ("user", 3),
        ("user", 3),
        ("user", 3),
        ("user", 3),
        ("assistant", 3),
        ("turn_end", 3),
        ("user", 4),
        ("assistant", 4),
        ("turn_end", 4),
        ("user", 5),
        ("assistant", 5),
        ("turn_end", 5),
    ]
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)


def test_streamed_records_of_one_message_become_one_step_even_when_results_interleave():
    steps = [e for e in _parse().events if isinstance(e, AssistantEvent)]
    assert [(s.turn, s.step) for s in steps] == [
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 1),
    ]
    first = steps[0]
    assert (first.text, first.stop_reason) == ("I'll list them.", "tool_use")
    assert [(c.call_id, c.name, c.arguments) for c in first.tool_calls] == [
        ("toolu_1", "Bash", '{"command":"ls"}')
    ]
    second = steps[1]
    assert second.text == ""
    assert [c.call_id for c in second.tool_calls] == ["toolu_2", "toolu_3"]
    assert (steps[2].text, steps[2].tool_calls, steps[2].stop_reason) == (
        "There are two files.",
        (),
        "end_turn",
    )


def test_a_message_cut_off_mid_stream_keeps_no_stop_reason():
    steps = [e for e in _parse().events if isinstance(e, AssistantEvent)]
    assert (steps[4].text, steps[4].stop_reason) == ("Watching.", None)


def test_tool_results_take_the_step_and_name_of_their_call():
    results = [e for e in _parse().events if isinstance(e, ToolResultEvent)]
    assert [(r.turn, r.step, r.call_id, r.name, r.is_error) for r in results] == [
        (1, 1, "toolu_1", "Bash", False),
        (1, 2, "toolu_2", "Read", False),
        (1, 2, "toolu_3", "Read", False),
        (2, 1, "toolu_4", "Bash", True),
    ]
    assert results[0].text == "a.py\nb.py\n[exit code: 0]"
    assert results[2].text == "print('b')\n[image]"


def test_every_assistant_step_precedes_its_results():
    events = _parse().events
    seq_of_step = {(e.turn, e.step): e.seq for e in events if isinstance(e, AssistantEvent)}
    for result in (e for e in events if isinstance(e, ToolResultEvent)):
        assert seq_of_step[(result.turn, result.step)] < result.seq


def test_human_prompts_include_queued_and_slash_commands_and_start_turns():
    users = [e for e in _parse().events if isinstance(e, UserEvent)]
    humans = [(u.turn, u.text) for u in users if u.origin == "human"]
    assert humans == [
        (1, "list the files in the repo"),
        (2, "delete b.py"),
        (2, "and a.py too"),
        (3, "/herdr watch tab 5"),
        (4, "thanks"),
        (5, "one more"),
    ]


def test_injected_user_records_are_harness_origin():
    users = [e for e in _parse().events if isinstance(e, UserEvent)]
    harness = [u.text[:22] for u in users if u.origin == "harness"]
    assert harness == [
        "Base directory for thi",
        "Only you see that comm",
        "<task-notification>\n<t",
        "Goal set: finish the c",
        "Base directory for thi",
        "/model fable",
        "<local-command-stdout>",
        "This session is being ",
        "<task-notification>\n<t",
    ]


def test_turn_ends_come_from_duration_interrupt_api_error_and_end_turn_fallback():
    ends = [e for e in _parse().events if isinstance(e, TurnEndEvent)]
    assert [(e.turn, e.reason) for e in ends] == [
        (1, "completed"),
        (2, "aborted"),
        (3, "error"),
        (4, "completed"),
        (5, "completed"),
    ]
    events = _parse().events
    last_step = max(e.seq for e in events if isinstance(e, AssistantEvent))
    assert ends[4].seq > last_step


def test_synthetic_and_sidechain_assistant_records_are_dropped():
    texts = [e.text for e in _parse().events if isinstance(e, AssistantEvent)]
    assert "No response requested." not in texts
    assert "I am a subagent." not in texts
    assert not any(text.startswith("API Error") for text in texts)


def test_tool_result_text_is_ansi_stripped_and_scrubbed():
    results = [e for e in _parse().events if isinstance(e, ToolResultEvent)]
    assert FAKE_SECRET not in results[3].text
    assert results[3].text.startswith("rm: b.py: Permission denied\n[exit code: 1]\nAWS_KEY=")
    assert "[REDACTED_SECRET]" in results[3].text


def test_scrub_off_keeps_secrets():
    results = [e for e in _parse(scrub=False).events if isinstance(e, ToolResultEvent)]
    assert FAKE_SECRET in results[3].text


def test_normalize_command_only_rewrites_command_wrappers():
    assert (
        normalize_command("<command-name>/x</command-name><command-args>a b</command-args>")
        == "/x a b"
    )
    assert normalize_command("<command-name>/x</command-name>") == "/x"
    assert normalize_command("plain <command-name>/x</command-name>") == (
        "plain <command-name>/x</command-name>"
    )


def test_malformed_line_raises_value_error_naming_the_line():
    lines = build_session_lines()
    lines.insert(4, "{not json")
    with pytest.raises(ValueError, match="line 5"):
        parse_claude_lines(lines, SOURCE)


def test_empty_log_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        parse_claude_lines(["", "  "], SOURCE)


def test_bookkeeping_only_log_has_no_events():
    lines = [build_session_lines()[0]]
    assert parse_claude_lines(lines, SOURCE).events == ()


def test_list_ids_finds_session_logs_and_ignores_subagent_and_memory_dirs(tmp_path):
    write_session_file(tmp_path, SESSION_ID)
    write_session_file(tmp_path, "0f0f0f0f-0000-4000-8000-000000000002")
    assert ClaudeSessionSource(tmp_path).list_ids() == [
        SESSION_ID,
        "0f0f0f0f-0000-4000-8000-000000000002",
    ]


def test_list_ids_on_a_missing_root_is_empty(tmp_path):
    assert ClaudeSessionSource(tmp_path / "nope").list_ids() == []


def test_load_reads_the_file_named_by_the_id(tmp_path):
    path = write_session_file(tmp_path, SESSION_ID)
    transcript = ClaudeSessionSource(tmp_path).load(SESSION_ID)
    assert transcript.header.source_path == str(path)
    assert transcript.header.transcript_id == SESSION_ID
    assert len(transcript.events) == 31


def test_the_delivery_queue_only_makes_a_typed_prompt_a_request():
    users = [e for e in _parse().events if isinstance(e, UserEvent)]
    queued = [u for u in users if u.text in ("and a.py too", "Goal set: finish the cleanup")]
    assert [(u.text, u.origin) for u in queued] == [
        ("and a.py too", "human"),
        ("Goal set: finish the cleanup", "harness"),
    ]
    notification = next(u for u in users if u.text.startswith("<task-notification>"))
    assert notification.origin == "harness"


def test_load_of_an_unknown_id_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ClaudeSessionSource(tmp_path).load("missing")


def test_source_exposes_the_harness_name(tmp_path):
    assert ClaudeSessionSource(tmp_path).harness == "claude"
