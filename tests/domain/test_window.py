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
            ToolResultEvent(
                11, 2, 1, "c2", "bash", "rm: b.py: Permission denied\n[exit code: 1]", True
            ),
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
        "results": [
            {"tool": "bash", "input": '{"command":"ls"}', "is_error": False, "text": "a.py\nb.py"}
        ],
    }
    assert "turn_evidence" not in s  # the previous step's results are the only ones this turn
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
    assert s["assistant_step"]["tool_calls"] == [{"tool": "bash", "arguments": '{"command":"ls"}'}]


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


def _three_step_turn(final_text="Done: a.py has 3 lines.", middle_text=""):
    """step 1 lists files, step 2 reads one, step 3 (turn-ending) summarizes."""
    middle_calls = () if middle_text else (ToolCall("c2", "bash", '{"command":"cat a.py"}'),)
    events = [
        UserEvent(1, 1, "how long is a.py", "human"),
        AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", '{"command":"ls"}'),), "toolUse"),
        ToolResultEvent(3, 1, 1, "c1", "bash", "a.py\nb.py", False),
        AssistantEvent(4, 1, 2, middle_text, middle_calls, "toolUse" if middle_calls else "stop"),
    ]
    if middle_calls:
        events.append(ToolResultEvent(5, 1, 2, "c2", "bash", "x\ny\nz", False))
    events += [AssistantEvent(6, 1, 3, final_text, (), "stop"), TurnEndEvent(7, 1, "completed")]
    return Transcript(TranscriptHeader("s1", "dsh", "/p"), tuple(events))


def test_results_carry_the_call_input():
    w2 = build_windows(_three_step_turn())[1]
    result = w2.previous_message.results[0]
    assert result.input == '{"command":"ls"}' and result.text == "a.py\nb.py"
    assert w2.to_state()["previous_message"]["results"][0]["input"] == '{"command":"ls"}'


def test_turn_ending_step_sees_earlier_results_of_the_turn():
    w1, w2, w3 = build_windows(_three_step_turn())
    assert w1.turn_evidence == () and w2.turn_evidence == ()
    assert w3.previous_message.source == "tools"
    assert [r.text for r in w3.previous_message.results] == ["x\ny\nz"]
    assert [(r.step, r.tool, r.input, r.text) for r in w3.turn_evidence] == [
        (1, "bash", '{"command":"ls"}', "a.py\nb.py")
    ]
    assert w3.to_state()["turn_evidence"] == [
        {
            "step": 1,
            "tool": "bash",
            "input": '{"command":"ls"}',
            "is_error": False,
            "text": "a.py\nb.py",
        }
    ]


def test_turn_evidence_when_the_previous_step_was_text_only():
    w3 = build_windows(_three_step_turn(middle_text="Let me summarize."))[2]
    assert w3.previous_message.source == "user"
    assert [r.step for r in w3.turn_evidence] == [1]


def test_turn_evidence_keeps_the_most_recent_results_within_the_total_budget():
    events = [UserEvent(1, 1, "run everything", "human")]
    seq = 2
    for step in range(1, 6):
        events.append(
            AssistantEvent(
                seq, 1, step, "", (ToolCall(f"c{step}", "bash", f"cmd{step}"),), "toolUse"
            )
        )
        events.append(
            ToolResultEvent(seq + 1, 1, step, f"c{step}", "bash", f"out{step}" + "." * 100, False)
        )
        seq += 2
    events += [
        AssistantEvent(seq, 1, 6, "All done.", (), "stop"),
        TurnEndEvent(seq + 1, 1, "completed"),
    ]
    t = Transcript(TranscriptHeader("s1", "dsh", "/p"), tuple(events))
    final = build_windows(t, Budget(turn_evidence_result=50, turn_evidence_total=170))[-1]
    # step 5 is previous_message; steps 4 and 3 fit the total budget (each about 80 chars:
    # 50 kept + the omitted-chars marker + the 4-char input), step 2 would exceed it
    assert [r.step for r in final.turn_evidence] == [3, 4]
    assert all(OMITTED_MARKER.split("{")[0] in r.text for r in final.turn_evidence)
    assert final.turn_evidence[-1].text.startswith("out4")


def test_turn_evidence_always_keeps_at_least_one_result():
    final = build_windows(
        _three_step_turn(), Budget(turn_evidence_result=4, turn_evidence_total=1)
    )[-1]
    assert [r.step for r in final.turn_evidence] == [1]


def test_turn_end_reason_comes_from_the_turn_end_event():
    ws = build_windows(_transcript())
    assert all(w.turn_end_reason == "completed" and w.turn_completed for w in ws)
    aborted = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "go", "human"),
            AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", "{}"),), "toolUse"),
            TurnEndEvent(3, 1, "aborted"),
            UserEvent(4, 2, "again", "human"),
            AssistantEvent(5, 2, 1, "working", (), None),
        ),
    )
    w1, w2 = build_windows(aborted)
    assert w1.ends_turn and w1.turn_end_reason == "aborted" and not w1.turn_completed
    assert w2.ends_turn and w2.turn_end_reason is None and not w2.turn_completed


def test_earlier_requests_keep_the_original_task_behind_a_follow_up():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "build the parser", "human"),
            AssistantEvent(2, 1, 1, "ok", (), "stop"),
            TurnEndEvent(3, 1, "completed"),
            UserEvent(4, 2, "skill catalog", "harness"),
            UserEvent(5, 2, "continue", "human"),
            AssistantEvent(6, 2, 1, "still parsing", (), "stop"),
            TurnEndEvent(7, 2, "completed"),
            UserEvent(8, 3, "also add tests", "human"),
            AssistantEvent(9, 3, 1, "tests", (), "stop"),
        ),
    )
    w1, w2, w3 = build_windows(t)
    assert w1.earlier_requests == () and "earlier_requests" not in w1.to_state()
    assert w2.user_request == "continue" and w2.earlier_requests == ("build the parser",)
    assert w3.earlier_requests == ("build the parser", "continue")
    assert w3.to_state()["earlier_requests"] == ["build the parser", "continue"]


def test_earlier_requests_are_bounded_in_count_and_length():
    events = []
    seq = 1
    for i in range(6):
        events.append(UserEvent(seq, i + 1, f"request {i} " + "x" * 50, "human"))
        events.append(AssistantEvent(seq + 1, i + 1, 1, "ok", (), "stop"))
        seq += 2
    t = Transcript(TranscriptHeader("s1", "dsh", "/p"), tuple(events))
    last = build_windows(t, Budget(earlier_request=12, earlier_requests_max=2))[-1]
    assert [r[:9] for r in last.earlier_requests] == ["request 3", "request 4"]
    assert all(OMITTED_MARKER.split("{")[0] in r for r in last.earlier_requests)


def test_turn_evidence_leaves_out_bookkeeping_tools():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "ship it", "human"),
            AssistantEvent(2, 1, 1, "", (ToolCall("c1", "todo_write", "{}"),), "toolUse"),
            ToolResultEvent(3, 1, 1, "c1", "todo_write", "Updated todo list", False),
            AssistantEvent(4, 1, 2, "", (ToolCall("c2", "bash", "pytest"),), "toolUse"),
            ToolResultEvent(5, 1, 2, "c2", "bash", "3 passed", False),
            AssistantEvent(6, 1, 3, "", (ToolCall("c3", "send_message", "{}"),), "toolUse"),
            ToolResultEvent(7, 1, 3, "c3", "send_message", "message delivered", False),
            AssistantEvent(8, 1, 4, "All green.", (), "stop"),
            TurnEndEvent(9, 1, "completed"),
        ),
    )
    final = build_windows(t)[-1]
    assert [r.tool for r in final.previous_message.results] == ["send_message"]
    assert [(r.step, r.tool, r.text) for r in final.turn_evidence] == [(2, "bash", "3 passed")]


def _interjected_turn():
    """The user asks for a publish, then asks something else while it is still running."""
    return Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "set up the repo", "human"),
            AssistantEvent(2, 1, 1, "done", (), "stop"),
            TurnEndEvent(3, 1, "completed"),
            UserEvent(4, 2, "publish to npm", "human"),
            AssistantEvent(
                5, 2, 1, "", (ToolCall("c1", "bash", '{"command":"npm publish"}'),), "toolUse"
            ),
            ToolResultEvent(6, 2, 1, "c1", "bash", "+ pkg@1.0.0", False),
            UserEvent(7, 2, "where is the authenticator code", "human"),
            AssistantEvent(8, 2, 2, "Published. Verifying the install.", (), "stop"),
            TurnEndEvent(9, 2, "completed"),
        ),
    )


def test_a_message_sent_after_the_turn_began_does_not_become_the_request():
    w1, publish, after = build_windows(_interjected_turn())
    assert w1.user_request == "set up the repo"
    assert publish.user_request == "publish to npm" and publish.interjections == ()
    assert after.user_request == "publish to npm"
    assert after.interjections == ("where is the authenticator code",)
    assert after.earlier_requests == ("set up the repo",)
    state = after.to_state()
    assert state["user_request"] == "publish to npm"
    assert state["interjections"] == ["where is the authenticator code"]
    assert "interjections" not in publish.to_state()


def test_an_interjection_opens_the_next_turn_when_the_turn_is_over():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "publish to npm", "human"),
            AssistantEvent(2, 1, 1, "published", (), "stop"),
            TurnEndEvent(3, 1, "completed"),
            UserEvent(4, 2, "where is the authenticator code", "human"),
            AssistantEvent(5, 2, 1, "in auth.py", (), "stop"),
        ),
    )
    _, answer = build_windows(t)
    assert answer.user_request == "where is the authenticator code"
    assert answer.interjections == () and answer.earlier_requests == ("publish to npm",)


def test_interjections_are_bounded_in_count_and_length():
    events = [
        UserEvent(1, 1, "start", "human"),
        AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", "{}"),), "toolUse"),
    ]
    seq = 3
    for i in range(4):
        events.append(UserEvent(seq, 1, f"note {i} " + "y" * 50, "human"))
        seq += 1
    events.append(AssistantEvent(seq, 1, 2, "ok", (), "stop"))
    t = Transcript(TranscriptHeader("s1", "dsh", "/p"), tuple(events))
    last = build_windows(t, Budget(interjection=10, interjections_max=2))[-1]
    assert [text[:6] for text in last.interjections] == ["note 2", "note 3"]
    assert all(OMITTED_MARKER.split("{")[0] in text for text in last.interjections)
    assert last.user_request == "start"


def test_a_step_that_says_something_mid_turn_sees_the_turn_evidence():
    """A narration step claims what the turn established, not only the previous result."""
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "run the suite", "human"),
            AssistantEvent(
                2, 1, 1, "", (ToolCall("c1", "bash", '{"command":"pytest"}'),), "toolUse"
            ),
            ToolResultEvent(3, 1, 1, "c1", "bash", "3 passed", False),
            AssistantEvent(4, 1, 2, "", (ToolCall("c2", "bash", '{"command":"ruff"}'),), "toolUse"),
            ToolResultEvent(5, 1, 2, "c2", "bash", "All checks passed", False),
            AssistantEvent(
                6,
                1,
                3,
                "Tests and lint are green. Now the build.",
                (ToolCall("c3", "bash", '{"command":"build"}'),),
                "toolUse",
            ),
            ToolResultEvent(7, 1, 3, "c3", "bash", "built", False),
            AssistantEvent(8, 1, 4, "Shipped.", (), "stop"),
            TurnEndEvent(9, 1, "completed"),
        ),
    )
    _, _, narration, final = build_windows(t)
    assert not narration.ends_turn
    assert [(r.step, r.text) for r in narration.turn_evidence] == [(1, "3 passed")]
    assert narration.to_state()["turn_evidence"][0]["text"] == "3 passed"
    assert [(r.step, r.text) for r in final.turn_evidence] == [
        (1, "3 passed"),
        (2, "All checks passed"),
    ]


def test_a_step_with_no_text_claims_nothing_and_gets_no_turn_evidence():
    t = Transcript(
        TranscriptHeader("s1", "dsh", "/p"),
        (
            UserEvent(1, 1, "run the suite", "human"),
            AssistantEvent(2, 1, 1, "", (ToolCall("c1", "bash", "{}"),), "toolUse"),
            ToolResultEvent(3, 1, 1, "c1", "bash", "3 passed", False),
            AssistantEvent(4, 1, 2, "", (ToolCall("c2", "bash", "{}"),), "toolUse"),
            ToolResultEvent(5, 1, 2, "c2", "bash", "ok", False),
            AssistantEvent(6, 1, 3, "   ", (ToolCall("c3", "bash", "{}"),), "toolUse"),
        ),
    )
    assert [w.turn_evidence for w in build_windows(t)] == [(), (), ()]
