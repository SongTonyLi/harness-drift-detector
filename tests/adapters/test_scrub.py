from harness_drift_detector.adapters.scrub import REDACTED, scrub_secrets, strip_ansi


def test_strip_ansi_removes_colour_codes():
    assert strip_ansi("\x1b[1mUsage:\x1b[0m") == "Usage:"


def test_strip_ansi_removes_cursor_and_osc_sequences():
    assert strip_ansi("a\x1b[2Kb\x1b]0;title\x07c") == "abc"


def test_strip_ansi_leaves_plain_text():
    assert strip_ansi("no escapes here") == "no escapes here"


def test_scrub_apikey_token():
    text = "export KEY=apikey_" + "A1b2C3d4E5f6G7h8I9j0"
    assert scrub_secrets(text) == "export KEY=" + REDACTED


def test_scrub_sk_token():
    assert scrub_secrets("token sk-" + "abcdefghij0123456789" + " end") == f"token {REDACTED} end"


def test_scrub_github_tokens():
    for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
        assert scrub_secrets(prefix + "0123456789abcdefghij") == REDACTED


def test_scrub_aws_access_key_id():
    assert scrub_secrets("id=" + "AKIA" + "0123456789ABCDEF.") == f"id={REDACTED}."


def test_scrub_slack_token():
    assert scrub_secrets("xoxb-" + "1234567890-0987654321-abcdefghijkl") == REDACTED


def test_scrub_bearer_keeps_the_word_bearer():
    header = "Authorization: Bearer " + "q" * 40
    assert scrub_secrets(header) == f"Authorization: Bearer {REDACTED}"


def test_scrub_leaves_ordinary_text_alone():
    text = "sk-short, a bash script, Bearer me, apikey_ nope, git push"
    assert scrub_secrets(text) == text


def test_scrub_handles_several_secrets_in_one_string():
    text = "a apikey_" + "b" * 20 + " and sk-" + "c" * 25 + " done"
    assert scrub_secrets(text) == f"a {REDACTED} and {REDACTED} done"
