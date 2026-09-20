from dataclasses import replace

from harness_drift_detector.domain.probes import (
    CATALOG,
    has_error_marker,
    select_probes,
)
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
    PreviousMessage,
    StepCall,
    ToolOutcome,
    Window,
    build_windows,
)


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
            ToolResultEvent(
                11, 2, 1, "c2", "bash", "rm: b.py: Permission denied\n[exit code: 1]", True
            ),
            AssistantEvent(12, 2, 2, "Done.", (), "stop"),
            TurnEndEvent(13, 2, "completed"),
        ),
    )


def _ids(window, only=None):
    return [p.id for p in select_probes(window, only)]


def test_has_error_marker_true_cases():
    assert has_error_marker("[exit code: 1]")
    assert has_error_marker("boom\n[exit code: 127]")
    assert has_error_marker("Traceback (most recent call last)\n  File ...")
    assert has_error_marker("rm: b.py: Permission denied")
    assert has_error_marker("bash: frobnicate: command not found")
    assert has_error_marker("cat: nope: No such file or directory")
    assert has_error_marker("Error: cannot parse")
    assert has_error_marker("error: cannot parse")
    assert has_error_marker("1 test FAILED")


def test_has_error_marker_false_cases():
    assert not has_error_marker("[exit code: 0]")
    assert not has_error_marker("all good")
    assert not has_error_marker("")
    assert not has_error_marker("no errors were found")


def test_select_probes_first_step_with_tool_call():
    w1 = build_windows(_transcript())[0]
    assert _ids(w1) == [
        "user.off_task",
        "adjacent.ignores_previous",
        "tool.unjustified_call",
        "drift.degree",
    ]


def test_select_probes_text_step_after_clean_tool_result():
    w2 = build_windows(_transcript())[1]
    ids = _ids(w2)
    assert ids == [
        "user.off_task",
        "adjacent.ignores_previous",
        "adjacent.self_discontinuity",
        "tool.unsupported_claim",
        "goal.premature_stop",
        "drift.degree",
    ]
    assert "tool.ignored_error" not in ids


def test_select_probes_after_error_result():
    w4 = build_windows(_transcript())[3]
    ids = _ids(w4)
    assert "tool.ignored_error" in ids
    assert "tool.unsupported_claim" in ids
    assert ids == [p for p in CATALOG if p in ids]


def test_select_probes_order_follows_catalog():
    for window in build_windows(_transcript()):
        ids = _ids(window)
        assert ids == [pid for pid in CATALOG if pid in ids]


def _window(**kwargs):
    base = dict(
        transcript_id="s1",
        turn=1,
        step=1,
        seq=1,
        user_request="do it",
        previous_message=PreviousMessage(source="user", text="do it"),
        previous_assistant_text="",
        assistant_text="working",
        tool_calls=(),
        ends_turn=False,
        turn_end_reason="completed",
    )
    base.update(kwargs)
    return Window(**base)


def test_select_probes_question_tool():
    w = _window(tool_calls=(StepCall("ask_user_question", '{"question":"which file?"}'),))
    ids = _ids(w)
    assert "goal.unnecessary_question" in ids
    assert "tool.unjustified_call" in ids


def test_select_probes_question_at_end_of_turn():
    w = _window(assistant_text="Which file should I delete?\n", ends_turn=True)
    ids = _ids(w)
    assert "goal.unnecessary_question" in ids
    assert "goal.premature_stop" in ids


def test_select_probes_no_question_when_turn_continues():
    w = _window(assistant_text="Which file should I delete?", ends_turn=False)
    assert "goal.unnecessary_question" not in _ids(w)


def test_unsupported_claim_needs_non_empty_text():
    tools = PreviousMessage(source="tools", results=(ToolOutcome("bash", False, "a.py"),))
    assert "tool.unsupported_claim" not in _ids(
        _window(previous_message=tools, assistant_text="  ")
    )
    assert "tool.unsupported_claim" in _ids(_window(previous_message=tools, assistant_text="ok"))


def test_ignored_error_from_marker_without_error_flag():
    tools = PreviousMessage(
        source="tools", results=(ToolOutcome("bash", False, "Traceback (most recent call last)"),)
    )
    assert "tool.ignored_error" in _ids(_window(previous_message=tools))


def test_only_filters_probes():
    w1 = build_windows(_transcript())[0]
    assert _ids(w1, {"user.off_task"}) == ["user.off_task"]
    assert _ids(w1, {"tool.ignored_error"}) == []
    assert _ids(w1, set()) == []


def test_selected_probes_come_from_the_catalog():
    for probe in select_probes(build_windows(_transcript())[1]):
        assert CATALOG[probe.id] is probe


def test_has_error_marker_matches_the_spec_markers():
    """The spec's marker list is literal: `Error:` / `error:` anywhere, and `No such file`."""
    assert has_error_marker("ValueError: invalid literal for int()")
    assert has_error_marker("TypeError: bad operand type")
    assert has_error_marker("cp: x: No such file")
    assert has_error_marker('{"error": "quota exceeded"}') is False  # no colon after "error"
    assert not has_error_marker("no errors were found")


def test_question_at_the_end_of_a_long_step_is_still_probed():
    long_question = "Here is a very long summary. " * 200 + "\n\nShould I also update the tests?"
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "refactor the parser", "human"),
            AssistantEvent(2, 1, 1, long_question, (), "stop"),
            TurnEndEvent(3, 1, "completed"),
        ),
    )
    assert "goal.unnecessary_question" in _ids(build_windows(t)[0])


def test_ignored_error_is_probed_when_the_failure_is_in_a_long_tool_result():
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
    assert "tool.ignored_error" in _ids(build_windows(t)[1])


def test_unsupported_claim_is_asked_for_a_final_step_with_turn_evidence():
    """A final summary after a text-only step still has tool results to be checked against."""
    from harness_drift_detector.domain.window import TurnResult

    base = build_windows(_transcript())[1]
    evidence = (TurnResult(step=1, tool="bash", input="ls", is_error=False, text="a.py"),)
    final = replace(
        base,
        previous_message=PreviousMessage(source="user", text="list the files"),
        turn_evidence=evidence,
        ends_turn=True,
    )
    assert "tool.unsupported_claim" in _ids(final)
    without_evidence = replace(final, turn_evidence=())
    assert "tool.unsupported_claim" not in _ids(without_evidence)
    silent = replace(final, assistant_text="")
    assert "tool.unsupported_claim" not in _ids(silent)


def test_off_task_is_not_asked_for_a_call_only_step():
    """Raw tool arguments against the request are not an off-task signal; the call is judged
    by tool.unjustified_call instead."""
    w3 = build_windows(_transcript())[2]
    assert w3.assistant_text == ""
    ids = _ids(w3)
    assert "user.off_task" not in ids and "tool.unjustified_call" in ids


def test_premature_stop_needs_a_turn_the_assistant_chose_to_end():
    final = build_windows(_transcript())[1]
    assert "goal.premature_stop" in _ids(final)
    assert "goal.premature_stop" not in _ids(replace(final, turn_end_reason="aborted"))
    assert "goal.premature_stop" not in _ids(replace(final, turn_end_reason="error"))
    assert "goal.premature_stop" not in _ids(replace(final, turn_end_reason=None))


def test_closing_question_is_only_a_question_when_the_turn_completed():
    final = replace(build_windows(_transcript())[1], assistant_text="Shall I continue?")
    assert "goal.unnecessary_question" in _ids(final)
    assert "goal.unnecessary_question" not in _ids(replace(final, turn_end_reason="aborted"))
    asked_by_tool = replace(
        final, turn_end_reason="aborted", tool_calls=(StepCall("ask_user_question", "{}"),)
    )
    assert "goal.unnecessary_question" in _ids(asked_by_tool)


def test_unsupported_claim_needs_evidence_from_a_real_tool():
    base = build_windows(_transcript())[1]
    bookkeeping = PreviousMessage(
        source="tools",
        results=(ToolOutcome("send_message", False, "message delivered"),),
    )
    assert "tool.unsupported_claim" not in _ids(replace(base, previous_message=bookkeeping))
    mixed = PreviousMessage(
        source="tools",
        results=(
            ToolOutcome("send_message", False, "message delivered"),
            ToolOutcome("bash", False, "3 passed"),
        ),
    )
    assert "tool.unsupported_claim" in _ids(replace(base, previous_message=mixed))


def test_ignored_error_is_not_asked_for_a_failed_skill_lookup():
    base = build_windows(_transcript())[1]
    lookup = PreviousMessage(
        source="tools",
        results=(ToolOutcome("skill", True, 'Error: skill "x" is unknown or no longer available'),),
    )
    assert "tool.ignored_error" not in _ids(replace(base, previous_message=lookup))
    real = PreviousMessage(
        source="tools", results=(ToolOutcome("bash", False, "boom\n[exit code: 1]"),)
    )
    assert "tool.ignored_error" in _ids(replace(base, previous_message=real))
