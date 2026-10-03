"""Heuristic secret detection reports where, never what. Token-shaped values are built at runtime."""

import pytest

from agentjury.change_secrets import scan, secret_env_values

AWS = "AKIA" + "Q" * 16
GITHUB = "ghp" + "_" + "a1B2" * 9
SLACK = "xoxb" + "-" + "1234567890-abcdef"
GOOGLE = "AIza" + "S" * 35
STRIPE = "sk" + "_live_" + "4" * 24
API = "sk-" + "proj-" + "Z9" * 20
JWT = ".".join(["eyJ" + "h" * 12, "eyJ" + "p" * 12, "s" * 16])
PRIVATE = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"


@pytest.mark.parametrize("text, rule", [
    (f"key = {PRIVATE}", "private_key"),
    (f"aws_id: {AWS}", "aws_access_key"),
    (f"token {GITHUB}", "github_token"),
    (f"slack {SLACK}", "slack_token"),
    (f"google {GOOGLE}", "google_api_key"),
    (f"stripe {STRIPE}", "stripe_live_key"),
    (f"OPENAI={API}", "api_key"),
    (f"auth: Bearer {JWT}", "jwt"),
    ('password = "hunter2hunter2"', "credential_assignment"),
    ("client_secret: 'q8Zr0x!t4LmP'", "credential_assignment"),
    ('{"api_key": "4f6b1c9e2d7a"}', "credential_assignment"),
])
def test_rules_report_location_not_value(text, rule):
    matches = scan([("diff:src/app.py", "first line\n" + text + "\n")], environ={})
    assert [(m.source, m.line, m.rule) for m in matches] == [("diff:src/app.py", 2, rule)]
    match = matches[0]
    assert match.id == f"diff:src/app.py@2:{rule}"
    secret = text.split()[-1].strip("'\"{}")
    for rendered in (match.id, match.describe(), repr(match), str(match)):
        assert secret not in rendered


@pytest.mark.parametrize("text", [
    'api_key = "<your-api-key>"', 'password: "changeme123"', 'secret = "${SECRET_VALUE}"',
    'token = "xxxxxxxxxxxx"', 'password = "short"', 'api_key = "your_api_key_here"',
    "OPENAI_API_KEY=sk-...", "def password_strength(value):", "sk-learn is a library",
])
def test_placeholders_and_ordinary_code_are_not_flagged(text):
    assert scan([("diff:a.py", text)], environ={}) == []


def test_environment_values_are_matched_by_secret_names_only():
    environ = {
        "MY_SERVICE_API_KEY": "v4lue-of-a-real-key-123",
        "GITHUB_TOKEN": "tokenvalue-0987654321",
        "GIT_AUTHOR_NAME": "Rashid Al-Derham",
        "SSH_AUTH_SOCK": "/tmp/ssh-agent.sock-12345",
        "SHORT_KEY": "tiny",
        "FEATURE_ENABLED": "true-but-long-enough",
    }
    assert secret_env_values(environ) == {"v4lue-of-a-real-key-123": "MY_SERVICE_API_KEY",
                                         "tokenvalue-0987654321": "GITHUB_TOKEN"}
    text = "author Rashid Al-Derham\nsock /tmp/ssh-agent.sock-12345\nx = 'v4lue-of-a-real-key-123'\n"
    matches = scan([("test-log", text)], environ=environ)
    assert [(m.line, m.rule, m.variable) for m in matches] == [(3, "environment_value", "MY_SERVICE_API_KEY")]
    assert "v4lue" not in matches[0].describe()
    assert "MY_SERVICE_API_KEY" in matches[0].describe()


def test_matches_are_per_source_and_deduplicated_per_line():
    text = f"a {GITHUB} b {GITHUB}\nclean\n{GITHUB}\n"
    matches = scan([("task", "clean task"), ("test-log", text)], environ={})
    assert [m.id for m in matches] == ["test-log@1:github_token", "test-log@3:github_token"]
