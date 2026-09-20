from harness_drift_detector.domain.transcript import (
    AssistantEvent,
    SystemEvent,
    ToolCall,
    ToolResultEvent,
    Transcript,
    TranscriptHeader,
    TurnEndEvent,
    UserEvent,
)
from harness_drift_detector.domain.window import (
    OMITTED_MARKER,
    Budget,
    build_windows,
    truncate,
)


def test_truncate_keeps_short_text():
    assert truncate("abc", 10, 5) == "abc"
    assert truncate("", 10, 5) == ""
    assert truncate("abcde", 5) == "abcde"


def test_truncate_head_tail_marker():
    out = truncate("a" * 100, 10, 5)
    assert out.startswith("a" * 10) and out.endswith("a" * 5)
    assert OMITTED_MARKER.format(n=85) in out


def test_truncate_head_only():
    out = truncate("b" * 30, 10)
    assert out.startswith("b" * 10)
    assert out.endswith(OMITTED_MARKER.format(n=20))


def _transcript():
    return Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            SystemEvent(1, 1, 1, "system prompt"),
            UserEvent(2, 1, "runtime snapshot", "harness"),
            UserEvent(3, 1, "list the files", "human"),
            UserEvent(4, 1, "skill catalog", "harness"),
            AssistantEvent(
                5, 1, 1, "I'll list them.", (ToolCall("c1", "bash", '{"command":"ls"}'),), "toolUse"
            ),
            ToolResultEvent(6, 1, 1, "c1", "bash", "a.py\nb.py", False),
            AssistantEvent(7, 1, 2, "There are two files.", (), "stop"),
            TurnEndEvent(8, 1, "completed"),
            UserEvent(9, 2, "delete b.py", "human"),
            AssistantEvent(
                10, 2, 1, "", (ToolCall("c2", "bash", '{"command":"rm b.py"}'),), "toolUse"
            ),
            ToolResultEvent(11, 2, 1, "c2", "bash", "rm: b.py: Permission denied\n[exit code: 1]", True),
            AssistantEvent(12, 2, 2, "Done.", (), "stop"),
            TurnEndEvent(13, 2, "completed"),
        ),
    )


def test_build_windows_shapes():
    ws = build_windows(_transcript())
    assert [w.window_id for w in ws] == ["s1:t1:s1", "s1:t1:s2", "s1:t2:s1", "s1:t2:s2"]
    w1, w2, w3, w4 = ws
    assert w1.user_request == "list the files"  # harness messages ignored
    assert w1.previous_message.source == "user" and w1.previous_message.text == "list the files"
    assert w1.previous_assistant_text == "" and not w1.ends_turn
    assert w1.tool_calls[0].tool == "bash"
    assert w1.tool_calls[0].arguments == '{"command":"ls"}'
    assert w1.seq == 5
    assert w2.previous_message.source == "tools"
    assert w2.previous_message.results[0].text == "a.py\nb.py"
    assert not w2.previous_message.results[0].is_error
    assert w2.previous_message.results[0].tool == "bash"
    assert w2.previous_assistant_text == "I'll list them." and w2.ends_turn
    assert w3.user_request == "delete b.py" and w3.previous_message.source == "user"
    assert w3.assistant_text == "" and not w3.ends_turn
    assert w4.previous_message.results[0].is_error and w4.ends_turn


def test_to_state_shape():
    w = build_windows(_transcript())[1]
    s = w.to_state()
    assert set(s) == {
        "user_request",
        "previous_message",
        "previous_assistant_text",
        "assistant_step",
    }
    assert s["previous_message"] == {
        "from": "tools",
        "results": [{"tool": "bash", "is_error": False, "text": "a.py\nb.py"}],
    }
    assert s["assistant_step"] == {
        "text": "There are two files.",
        "tool_calls": [],
        "ends_turn": True,
    }
    assert s["user_request"] == "list the files"
    assert s["previous_assistant_text"] == "I'll list them."


def test_to_state_user_previous_message():
    s = build_windows(_transcript())[0].to_state()
    assert s["previous_message"] == {"from": "user", "text": "list the files"}
    assert s["assistant_step"]["tool_calls"] == [
        {"tool": "bash", "arguments": '{"command":"ls"}'}
    ]


def test_budget_applies():
    t = _transcript()
    ws = build_windows(t, Budget(user_request=5))
    assert OMITTED_MARKER.split("{")[0] in ws[0].user_request


def test_budget_truncates_results_and_arguments():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "go", "human"),
            AssistantEvent(2, 1, 1, "x" * 50, (ToolCall("c1", "bash", "y" * 50),), "toolUse"),
            ToolResultEvent(3, 1, 1, "c1", "bash", "z" * 50, False),
            AssistantEvent(4, 1, 2, "done", (), "stop"),
        ),
    )
    budget = Budget(
        tool_result_head=4,
        tool_result_tail=2,
        previous_assistant_text=6,
        assistant_text=8,
        arguments=3,
    )
    w1, w2 = build_windows(t, budget)
    # the step text budget is spent head (6) and tail (2), so the ending survives
    assert w1.assistant_text == "x" * 6 + OMITTED_MARKER.format(n=42) + "xx"
    assert w1.tool_calls[0].arguments == "yyy" + OMITTED_MARKER.format(n=47)
    assert w2.previous_message.results[0].text == "zzzz" + OMITTED_MARKER.format(n=44) + "zz"
    assert w2.previous_assistant_text.startswith("x" * 6)


def test_text_only_previous_step_falls_back_to_user_request():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "explain", "human"),
            AssistantEvent(2, 1, 1, "First part.", (), None),
            AssistantEvent(3, 1, 2, "Second part.", (), "stop"),
        ),
    )
    w1, w2 = build_windows(t)
    assert w2.previous_message.source == "user" and w2.previous_message.text == "explain"
    assert w2.previous_assistant_text == "First part."
    assert w1.ends_turn is False and w2.ends_turn is True


def test_calls_without_results_give_empty_tools_message():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "go", "human"),
            AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", "{}"),), "toolUse"),
            AssistantEvent(3, 1, 2, "no result came back", (), "stop"),
        ),
    )
    w2 = build_windows(t)[1]
    assert w2.previous_message.source == "tools"
    assert w2.previous_message.results == ()
    assert w2.to_state()["previous_message"] == {"from": "tools", "results": []}


def test_results_are_ordered_by_previous_call_order_and_include_step_matches():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "go", "human"),
            AssistantEvent(
                2,
                1,
                1,
                "",
                (ToolCall("a", "read", "{}"), ToolCall("b", "bash", "{}")),
                "toolUse",
            ),
            ToolResultEvent(3, 1, 1, "b", "bash", "second call", False),
            ToolResultEvent(4, 1, 1, "a", "read", "first call", False),
            ToolResultEvent(5, 1, 1, "stray", "grep", "same step, unknown id", False),
            AssistantEvent(6, 1, 2, "ok", (), "stop"),
        ),
    )
    results = build_windows(t)[1].previous_message.results
    assert [r.text for r in results] == ["first call", "second call", "same step, unknown id"]
    assert [r.tool for r in results] == ["read", "bash", "grep"]


def test_no_human_message_yet_gives_empty_user_request():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "runtime snapshot", "harness"),
            AssistantEvent(2, 1, 1, "hello", (), "stop"),
        ),
    )
    w = build_windows(t)[0]
    assert w.user_request == ""
    assert w.previous_message.source == "user" and w.previous_message.text == ""


def test_no_assistant_events_gives_no_windows():
    t = Transcript(TranscriptHeader("s1", "dsh", "/p"), (UserEvent(1, 1, "hi", "human"),))
    assert build_windows(t) == []


def test_long_assistant_text_keeps_its_ending():
    """Head-only truncation would hide the end of a long step, where the conclusions and
    the wrap-up question live."""
    text = "x" * 4100 + " Which file do you want me to delete?"
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "delete something", "human"),
            AssistantEvent(2, 1, 1, text, (), "stop"),
        ),
    )
    w = build_windows(t)[0]
    assert len(w.assistant_text) <= Budget().assistant_text + len(OMITTED_MARKER.format(n=0)) + 4
    assert w.assistant_text.startswith("x" * 100)
    assert w.assistant_text.rstrip().endswith("Which file do you want me to delete?")
    assert OMITTED_MARKER.split("{")[0] in w.assistant_text


def test_error_marker_in_a_long_tool_result_survives_truncation():
    """A failure buried in the omitted middle of a long result must still be visible."""
    big = "ok\n" * 700 + "Traceback (most recent call last)\n" + "more\n" * 700
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "run the tests", "human"),
            AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", "{}"),), "toolUse"),
            ToolResultEvent(3, 1, 1, "c1", "bash", big, False),
            AssistantEvent(4, 1, 2, "All good, tests pass.", (), "stop"),
        ),
    )
    result = build_windows(t)[1].previous_message.results[0]
    assert "Traceback (most recent call last)" in result.text
    assert result.is_error is False  # the harness did not flag it; only the text shows it


def test_untruncated_tool_result_text_is_left_alone():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "run the tests", "human"),
            AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", "{}"),), "toolUse"),
            ToolResultEvent(3, 1, 1, "c1", "bash", "Traceback (most recent call last)", False),
            AssistantEvent(4, 1, 2, "done", (), "stop"),
        ),
    )
    assert build_windows(t)[1].previous_message.results[0].text == (
        "Traceback (most recent call last)"
    )
