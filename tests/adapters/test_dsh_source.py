import pytest

from harness_drift_detector.adapters.dsh_source import (
    DshSessionSource,
    parse_v3_lines,
    read_v3_file,
)
from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    SystemEvent,
    ToolResultEvent,
    TurnEndEvent,
    UserEvent,
)
from tests.fixtures.dsh_v3 import (
    CREATED_AT,
    CWD,
    FAKE_SECRET,
    MODEL,
    PROVIDER,
    build_session_lines,
    write_session_dir,
)


def _parse(**kwargs):
    return parse_v3_lines(build_session_lines(), "/fixture/session.v3.jsonl", **kwargs)


def test_header_comes_from_session_and_request_context():
    header = _parse().header
    assert header.transcript_id == "session-fixture"
    assert header.harness == "dsh"
    assert header.source_path == "/fixture/session.v3.jsonl"
    assert (header.model, header.provider) == (MODEL, PROVIDER)
    assert (header.cwd, header.created_at) == (CWD, CREATED_AT)


def test_event_kinds_in_seq_order_ignore_unknown_types():
    events = _parse().events
    assert [(e.kind, e.seq) for e in events] == [
        ("system", 7),
        ("user", 8),
        ("user", 9),
        ("user", 10),
        ("assistant", 15),
        ("tool_result", 17),
        ("assistant", 20),
        ("turn_end", 22),
        ("user", 25),
        ("assistant", 26),
        ("tool_result", 28),
        ("assistant", 31),
        ("tool_result", 32),
        ("turn_end", 34),
    ]


def test_user_messages_carry_turn_and_origin():
    users = [e for e in _parse().events if isinstance(e, UserEvent)]
    assert [(u.turn, u.origin) for u in users] == [
        (1, "human"),
        (1, "harness"),
        (1, "harness"),
        (2, "human"),
    ]
    assert users[0].text == "list the files in the repo"
    assert users[3].text == "delete b.py"


def test_system_event_keeps_turn_and_step():
    system = next(e for e in _parse().events if isinstance(e, SystemEvent))
    assert (system.turn, system.step, system.text) == (1, 1, "You are a coding agent.")


def test_assistant_steps_carry_text_calls_and_stop_reason():
    steps = [e for e in _parse().events if isinstance(e, AssistantEvent)]
    first = steps[0]
    assert (first.turn, first.step, first.text, first.stop_reason) == (1, 1, "I'll list them.", "toolUse")
    assert first.tool_calls[0].call_id == "call_1|fc_1"
    assert (first.tool_calls[0].name, first.tool_calls[0].arguments) == ("bash", '{"command":"ls"}')
    assert (steps[1].text, steps[1].tool_calls, steps[1].stop_reason) == ("There are two files.", (), "stop")
    assert steps[2].text == "" and steps[2].tool_calls[0].name == "bash"
    assert steps[3].stop_reason is None
    assert steps[3].tool_calls[0].name == "ask_user_question"


def test_tool_results_take_name_from_the_call_and_default_is_error_false():
    results = [e for e in _parse().events if isinstance(e, ToolResultEvent)]
    assert [(r.turn, r.step, r.name, r.is_error) for r in results] == [
        (1, 1, "bash", False),
        (2, 1, "bash", True),
        (2, 2, "ask_user_question", False),
    ]
    assert results[0].call_id == "call_1|fc_1"


def test_turn_end_reason_is_flattened():
    ends = [e for e in _parse().events if isinstance(e, TurnEndEvent)]
    assert [(e.turn, e.reason) for e in ends] == [(1, "completed"), (2, "completed")]


def test_tool_result_text_is_ansi_stripped_and_scrubbed():
    results = [e for e in _parse().events if isinstance(e, ToolResultEvent)]
    assert results[0].text == "a.py\nb.py\n[exit code: 0]"
    assert FAKE_SECRET not in results[1].text
    assert results[1].text.startswith("rm: b.py: Permission denied\n[exit code: 1]\nAWS_KEY=[REDACTED_SECRET]")


def test_scrub_off_keeps_secrets_but_still_strips_ansi():
    results = [e for e in _parse(scrub=False).events if isinstance(e, ToolResultEvent)]
    assert results[0].text == "a.py\nb.py\n[exit code: 0]"
    assert FAKE_SECRET in results[1].text


def test_malformed_line_raises_value_error_naming_the_line():
    lines = build_session_lines()
    lines.insert(5, "{not json")
    with pytest.raises(ValueError, match="line 6"):
        parse_v3_lines(lines, "/fixture/session.v3.jsonl")


def test_non_v3_session_is_rejected():
    lines = build_session_lines()
    lines[0] = lines[0].replace('"version": 3', '"version": 2')
    with pytest.raises(ValueError, match="version"):
        parse_v3_lines(lines, "/fixture/session.v3.jsonl")


def test_missing_session_header_is_rejected():
    lines = build_session_lines()[1:]
    with pytest.raises(ValueError, match="session"):
        parse_v3_lines(lines, "/fixture/session.v3.jsonl")


def test_list_ids_finds_raw_and_zstd_sessions_and_skips_empty_dirs(tmp_path):
    write_session_dir(tmp_path, "session-raw", compressed=False)
    write_session_dir(tmp_path, "session-zstd", compressed=True)
    (tmp_path / "session-empty").mkdir()
    (tmp_path / "session-empty" / "session.lock").write_text("")
    assert DshSessionSource(tmp_path).list_ids() == ["session-raw", "session-zstd"]


def test_list_ids_on_a_missing_root_is_empty(tmp_path):
    assert DshSessionSource(tmp_path / "nope").list_ids() == []


def test_load_of_a_zstd_session_matches_the_raw_one(tmp_path):
    write_session_dir(tmp_path, "session-raw", compressed=False)
    write_session_dir(tmp_path, "session-zstd", compressed=True)
    source = DshSessionSource(tmp_path)
    raw = source.load("session-raw")
    packed = source.load("session-zstd")
    assert raw.events == packed.events
    assert packed.header.source_path.endswith("session.v3.jsonl.zstd")
    assert raw.header.source_path.endswith("session.v3.jsonl")
    assert raw.header.transcript_id == "session-raw"


def test_load_prefers_the_raw_file_when_both_exist(tmp_path):
    directory = write_session_dir(tmp_path, "session-both", compressed=False)
    write_session_dir(tmp_path, "session-both", compressed=True)
    assert (directory / "session.v3.jsonl").exists()
    assert (directory / "session.v3.jsonl.zstd").exists()
    assert DshSessionSource(tmp_path).load("session-both").header.source_path.endswith(".jsonl")


def test_load_of_an_unknown_id_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        DshSessionSource(tmp_path).load("session-missing")


def test_read_v3_file_yields_lines_for_both_encodings(tmp_path):
    raw_dir = write_session_dir(tmp_path, "session-raw", compressed=False)
    zstd_dir = write_session_dir(tmp_path, "session-zstd", compressed=True)
    raw_lines = list(read_v3_file(raw_dir / "session.v3.jsonl"))
    packed_lines = list(read_v3_file(zstd_dir / "session.v3.jsonl.zstd"))
    assert len(raw_lines) == len(packed_lines) == len(build_session_lines())
    assert raw_lines[0].startswith('{"type": "session"')


def test_source_exposes_the_harness_name(tmp_path):
    assert DshSessionSource(tmp_path).harness == "dsh"
