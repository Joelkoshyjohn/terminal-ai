import io
import subprocess

import pytest

from aiterminal import executor
from aiterminal.executor import (
    MAX_STREAM_BYTES,
    CommandExecutionError,
    CommandProposal,
    CommandValidationError,
    ExecutionResult,
    execute_proposal,
    output_for_ai,
)


@pytest.mark.parametrize(
    ("action", "arguments"),
    [
        ("python_version", {}),
        ("install_python", {}),
        ("create_directory", {"path": "new-folder"}),
        ("list_directory", {"path": "."}),
        ("pip_install", {"package": "example-package"}),
        ("create_venv", {"path": "new-env"}),
        ("run_python_script", {"path": "script.py"}),
    ],
)
def test_allowlisted_actions_parse(action, arguments):
    assert CommandProposal.from_payload({"action": action, "arguments": arguments}) == CommandProposal(
        action, arguments
    )


@pytest.mark.parametrize(
    "payload",
    [
        "python --version",
        {"action": "shell", "arguments": {"command": "whoami"}},
        {"action": "delete", "arguments": {"path": "."}},
        {"action": "run_python_script", "arguments": {"path": "script.py", "command": "extra"}},
        {"action": "pip_install", "arguments": {"package": "--index-url=https://evil.test"}},
        {"action": "pip_install", "arguments": {"package": "https://example.test/package.whl"}},
        {"action": "create_directory", "arguments": {"path": "../outside"}},
        {"action": "python_version", "arguments": {"args": ["--version"]}},
    ],
)
def test_rejects_non_allowlisted_or_malformed_actions(payload):
    with pytest.raises(CommandValidationError):
        CommandProposal.from_payload(payload)


def test_executor_revalidates_even_directly_constructed_proposals():
    unsafe = CommandProposal("shell", {"command": "whoami"})
    with pytest.raises(CommandValidationError):
        execute_proposal(unsafe)


def test_directory_actions_create_and_list_only_after_validation(tmp_path):
    target = tmp_path / "created"
    create = CommandProposal.from_payload(
        {"action": "create_directory", "arguments": {"path": str(target)}}
    )
    result = execute_proposal(create)
    assert target.is_dir()
    assert result.exit_code == 0
    assert str(target) in result.stdout

    listed = CommandProposal.from_payload(
        {"action": "list_directory", "arguments": {"path": str(tmp_path)}}
    )
    listing = execute_proposal(listed)
    assert "created" in listing.stdout


class FakeProcess:
    def __init__(self, *, stdout=b"Python 3.14.6\n", stderr=b"", timeout=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.timeout = timeout
        self.killed = False
        self.wait_calls = 0

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.timeout and self.wait_calls == 1:
            raise subprocess.TimeoutExpired("python", timeout)
        return -9 if self.killed else 0

    def kill(self):
        self.killed = True


def test_subprocess_uses_shell_false_and_does_not_inherit_secret_environment(monkeypatch):
    process = FakeProcess()
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return process

    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("API_TOKEN", "local-secret")
    proposal = CommandProposal.from_payload({"action": "python_version", "arguments": {}})
    result = execute_proposal(proposal)

    assert result.stdout == "Python 3.14.6\n"
    assert captured["shell"] is False
    assert captured["command"] == [executor.sys.executable, "--version"]
    assert "API_TOKEN" not in captured["env"]


def test_subprocess_timeout_is_reported_and_terminates_process(monkeypatch):
    process = FakeProcess(stdout=b"still working", timeout=True)
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *_args, **_kwargs: process)

    result = execute_proposal(CommandProposal.from_payload({"action": "python_version", "arguments": {}}))

    assert result.timed_out
    assert result.exit_code is None
    assert result.stdout == "still working"
    assert process.killed


def test_subprocess_output_is_bounded(monkeypatch):
    process = FakeProcess(stdout=b"x" * (MAX_STREAM_BYTES + 100))
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *_args, **_kwargs: process)

    result = execute_proposal(CommandProposal.from_payload({"action": "python_version", "arguments": {}}))

    assert len(result.stdout.encode("utf-8")) <= MAX_STREAM_BYTES
    assert result.stdout.endswith("[output truncated]")


def test_startup_error_is_reported(monkeypatch):
    def fail_to_start(*_args, **_kwargs):
        raise FileNotFoundError("missing executable")

    monkeypatch.setattr(executor.subprocess, "Popen", fail_to_start)
    with pytest.raises(CommandExecutionError, match="Could not start"):
        execute_proposal(CommandProposal.from_payload({"action": "python_version", "arguments": {}}))


def test_nonzero_process_exit_and_sensitive_output_redaction(monkeypatch):
    process = FakeProcess(stdout=b"API_TOKEN=local-secret\n")
    process.wait = lambda timeout=None: 2
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setenv("API_TOKEN", "local-secret")

    result = execute_proposal(CommandProposal.from_payload({"action": "python_version", "arguments": {}}))

    assert result.exit_code == 2
    assert "local-secret" not in output_for_ai(result)
    assert "[REDACTED]" in output_for_ai(result)


def test_unsupported_python_install_platform_fails_without_running(monkeypatch):
    monkeypatch.setattr(executor.os, "name", "posix")
    proposal = CommandProposal.from_payload({"action": "install_python", "arguments": {}})
    with pytest.raises(CommandValidationError, match="only on Windows"):
        execute_proposal(proposal)


def test_run_script_requires_an_existing_python_file(tmp_path):
    proposal = CommandProposal.from_payload(
        {"action": "run_python_script", "arguments": {"path": str(tmp_path / "missing.py")}}
    )
    with pytest.raises(CommandExecutionError, match="Not an existing Python script"):
        execute_proposal(proposal)


def test_output_for_ai_masks_common_credentials():
    result = ExecutionResult(
        stdout="Bearer abcdefghijklmnop and sk-abcdefghijklmnop\nAWS_ACCESS_KEY_ID=plainvalue",
        stderr="",
        exit_code=0,
    )
    output = output_for_ai(result)
    assert "abcdefghijklmnop" not in output
    assert "plainvalue" not in output
    assert "[REDACTED]" in output
