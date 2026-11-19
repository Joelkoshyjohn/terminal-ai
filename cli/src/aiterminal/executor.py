"""Validated local actions proposed by the AITerminal assistant."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

MAX_STREAM_BYTES = 16_384
DEFAULT_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 300

_PACKAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH|BEARER)",
    re.I,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)([A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?key|private[_-]?key|token|secret|password|credential|authorization)"
    r"[A-Za-z0-9_.-]*)(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_COMMON_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)


class CommandValidationError(ValueError):
    """The AI proposal is not in the local executor's safe command set."""


class CommandExecutionError(RuntimeError):
    """An allowed local action could not be started or completed."""


@dataclass(frozen=True)
class CommandProposal:
    action: str
    arguments: dict[str, str]

    @classmethod
    def from_payload(cls, payload: object) -> CommandProposal:
        if not isinstance(payload, dict) or set(payload) != {"action", "arguments"}:
            raise CommandValidationError("The command proposal has an invalid structure.")
        action = payload["action"]
        arguments = payload["arguments"]
        if not isinstance(action, str) or not isinstance(arguments, dict):
            raise CommandValidationError("The command proposal has an invalid structure.")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in arguments.items()):
            raise CommandValidationError("Command arguments must be strings.")

        required_arguments = {
            "python_version": set(),
            "install_python": set(),
            "create_directory": {"path"},
            "list_directory": {"path"},
            "pip_install": {"package"},
            "create_venv": {"path"},
            "run_python_script": {"path"},
        }
        if action not in required_arguments:
            raise CommandValidationError(f"Unsupported local action: {action!r}.")
        if set(arguments) != required_arguments[action]:
            raise CommandValidationError("The command proposal contains missing or unexpected arguments.")

        if action in {"create_directory", "list_directory", "create_venv", "run_python_script"}:
            cls._validate_path(arguments["path"])
        elif action == "pip_install" and not _PACKAGE_NAME.fullmatch(arguments["package"]):
            raise CommandValidationError("Only a package name from the configured Python package index is allowed.")
        return cls(action=action, arguments=dict(arguments))

    @staticmethod
    def _validate_path(value: str) -> None:
        if not value or len(value) > 1_024 or "\x00" in value:
            raise CommandValidationError("A valid local path is required.")
        if ".." in Path(value).parts:
            raise CommandValidationError("Parent-directory path segments are not allowed.")
        _resolve_path(value)


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool = False


@dataclass
class _StreamCapture:
    data: bytearray = field(default_factory=bytearray)
    truncated: bool = False


def describe_proposal(proposal: CommandProposal) -> str:
    """Return a reviewable description of the exact operation to be performed."""
    proposal = _revalidate_proposal(proposal)
    action = proposal.action
    args = proposal.arguments
    if action == "python_version":
        return _format_argv([sys.executable, "--version"])
    if action == "install_python":
        executable = shutil.which("winget")
        if os.name != "nt":
            raise CommandValidationError("Installing Python is currently supported only on Windows.")
        if not executable:
            raise CommandExecutionError("Windows winget was not found; Python cannot be installed.")
        return _format_argv(
            [
                executable,
                "install",
                "--id",
                "Python.Python.3.12",
                "--exact",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        )
    if action == "pip_install":
        return _format_argv(
            [sys.executable, "-m", "pip", "install", "--only-binary=:all:", "--", args["package"]]
        )
    if action == "create_venv":
        return _format_argv([sys.executable, "-m", "venv", str(_resolve_path(args["path"]))])
    if action == "run_python_script":
        return _format_argv([sys.executable, str(_resolve_path(args["path"]))])
    if action == "create_directory":
        return f"Create directory and any missing parents (fails if it already exists): {_resolve_path(args['path'])}"
    if action == "list_directory":
        return f"List entries in directory: {_resolve_path(args['path'])}"
    raise CommandValidationError(f"Unsupported local action: {action!r}.")


def execute_proposal(proposal: CommandProposal) -> ExecutionResult:
    """Run one validated local action without invoking a shell."""
    proposal = _revalidate_proposal(proposal)
    action = proposal.action
    args = proposal.arguments

    if action == "create_directory":
        path = _resolve_path(args["path"])
        try:
            path.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise CommandExecutionError(f"Could not create directory {path}: {exc}") from exc
        return ExecutionResult(stdout=f"Created directory: {path}", stderr="", exit_code=0)

    if action == "list_directory":
        path = _resolve_path(args["path"])
        if not path.is_dir():
            raise CommandExecutionError(f"Not a directory: {path}")
        try:
            entries = []
            total_bytes = 0
            truncated = False
            for entry in path.iterdir():
                line = entry.name + (os.sep if entry.is_dir() else "")
                encoded = (line + "\n").encode("utf-8", errors="replace")
                if total_bytes + len(encoded) > MAX_STREAM_BYTES:
                    truncated = True
                    break
                entries.append(line)
                total_bytes += len(encoded)
        except OSError as exc:
            raise CommandExecutionError(f"Could not list directory {path}: {exc}") from exc
        output = "\n".join(entries)
        if truncated:
            output = _append_truncation_marker(output)
        return ExecutionResult(stdout=output, stderr="", exit_code=0)

    if action == "install_python":
        if os.name != "nt":
            raise CommandValidationError("Installing Python is currently supported only on Windows.")
        winget = shutil.which("winget")
        if not winget:
            raise CommandExecutionError("Windows winget was not found; Python was not installed.")
        command = [
            winget,
            "install",
            "--id",
            "Python.Python.3.12",
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        return _run_process(command, INSTALL_TIMEOUT_SECONDS)

    if action == "python_version":
        return _run_process([sys.executable, "--version"], DEFAULT_TIMEOUT_SECONDS)

    if action == "pip_install":
        return _run_process(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--only-binary=:all:",
                "--",
                args["package"],
            ],
            INSTALL_TIMEOUT_SECONDS,
        )

    if action == "create_venv":
        path = _resolve_path(args["path"])
        if path.exists():
            raise CommandExecutionError(f"Virtual environment target already exists: {path}")
        return _run_process([sys.executable, "-m", "venv", str(path)], INSTALL_TIMEOUT_SECONDS)

    if action == "run_python_script":
        path = _resolve_path(args["path"])
        if path.suffix.lower() != ".py" or not path.is_file():
            raise CommandExecutionError(f"Not an existing Python script: {path}")
        return _run_process([sys.executable, str(path)], DEFAULT_TIMEOUT_SECONDS, cwd=str(path.parent))

    raise CommandValidationError(f"Unsupported local action: {action!r}.")


def output_for_ai(result: ExecutionResult) -> str:
    """Mask likely credentials and inherited secret environment values before disclosure."""
    output = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\nexit code: {result.exit_code}"
    for name, value in os.environ.items():
        if _SENSITIVE_ENV_NAME.search(name) and value:
            output = output.replace(value, "[REDACTED]")
    output = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", output)
    output = _BEARER_TOKEN.sub("Bearer [REDACTED]", output)
    output = _COMMON_TOKEN.sub("[REDACTED TOKEN]", output)
    output = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", output)
    if len(output.encode("utf-8", errors="replace")) > MAX_STREAM_BYTES:
        return _append_truncation_marker(output)
    return output


def _format_argv(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def _revalidate_proposal(proposal: CommandProposal) -> CommandProposal:
    return CommandProposal.from_payload({"action": proposal.action, "arguments": proposal.arguments})


def _resolve_path(value: str) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise CommandValidationError("The requested local path could not be resolved.") from exc


def _child_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "LANG",
        "LC_ALL",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _run_process(command: list[str], timeout: int, *, cwd: str | None = None) -> ExecutionResult:
    try:
        process = subprocess.Popen(
            command,
            shell=False,
            cwd=cwd,
            env=_child_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise CommandExecutionError(f"Could not start the approved command: {exc}") from exc

    stdout_state = _StreamCapture()
    stderr_state = _StreamCapture()
    assert process.stdout is not None
    assert process.stderr is not None
    readers = (
        threading.Thread(target=_drain_stream, args=(process.stdout, stdout_state), daemon=True),
        threading.Thread(target=_drain_stream, args=(process.stderr, stderr_state), daemon=True),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        exit_code = None
        process.wait()
    for reader in readers:
        reader.join(timeout=1)

    stdout = _decode_stream(stdout_state)
    stderr = _decode_stream(stderr_state)
    return ExecutionResult(stdout=stdout, stderr=stderr, exit_code=exit_code, timed_out=timed_out)


def _drain_stream(stream: IO[bytes], state: _StreamCapture) -> None:
    while True:
        chunk = stream.read(8_192)
        if not chunk:
            return
        remaining = MAX_STREAM_BYTES - len(state.data)
        if remaining > 0:
            state.data.extend(chunk[:remaining])
        if len(chunk) > remaining:
            state.truncated = True


def _decode_stream(state: _StreamCapture) -> str:
    text = bytes(state.data).decode("utf-8", errors="replace")
    if state.truncated:
        return _append_truncation_marker(text)
    return text


def _append_truncation_marker(text: str) -> str:
    marker = "\n[output truncated]"
    encoded = text.encode("utf-8", errors="replace")
    marker_bytes = marker.encode("utf-8")
    if len(encoded) + len(marker_bytes) <= MAX_STREAM_BYTES:
        return text + marker
    return encoded[: MAX_STREAM_BYTES - len(marker_bytes)].decode("utf-8", errors="ignore") + marker
