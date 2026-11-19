from unittest.mock import patch

from typer.testing import CliRunner

from aiterminal import main as main_module
from aiterminal.client import ChatResponse
from aiterminal.executor import ExecutionResult


class FakeClient:
    def __init__(self, proposal=None):
        self.history_seen = []
        self.explanation_requests = []
        self.proposal = proposal

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def ask_with_proposal(self, question, history):
        self.history_seen.append((question, list(history)))
        return ChatResponse("answer", self.proposal)

    def ask(self, question, history):
        self.explanation_requests.append((question, list(history)))
        return "explained result"


def test_cli_starts_without_authentication():
    client = FakeClient()
    runner = CliRunner()
    with (
        patch.object(main_module, "AITerminalClient", return_value=client),
        patch.object(main_module, "run_conversation") as conversation,
    ):
        result = runner.invoke(main_module.app, [])
    assert result.exit_code == 0
    assert "Connecting to AITerminal Cloud..." in result.output
    assert "AITerminal ready!" in result.output
    assert "password" not in result.output.lower()
    conversation.assert_called_once_with(client)


def test_conversation_exit_and_context_are_session_local():
    client = FakeClient()
    questions = iter(["first", "second", "exit"])
    with (
        patch.object(main_module, "ask_question", side_effect=lambda: next(questions)),
        patch.object(main_module, "show_answer"),
        patch.object(main_module.console, "status") as status,
        patch.object(main_module.console, "print"),
    ):
        status.return_value.__enter__.return_value = None
        main_module.run_conversation(client)
    assert client.history_seen[0] == ("first", [])
    assert client.history_seen[1] == (
        "second",
        [{"role": "user", "content": "first"}, {"role": "assistant", "content": "answer"}],
    )


def test_clear_command_resets_context_and_clears_screen():
    client = FakeClient()
    questions = iter(["first", "clear", "second", "quit"])
    with (
        patch.object(main_module, "ask_question", side_effect=lambda: next(questions)),
        patch.object(main_module, "show_answer"),
        patch.object(main_module.console, "status") as status,
        patch.object(main_module.console, "clear") as clear_screen,
        patch.object(main_module.console, "print"),
    ):
        status.return_value.__enter__.return_value = None
        main_module.run_conversation(client)
    assert client.history_seen[0] == ("first", [])
    assert client.history_seen[1] == ("second", [])
    clear_screen.assert_called_once_with()


def test_rejecting_a_proposal_never_executes_it_or_sends_another_request():
    client = FakeClient({"action": "python_version", "arguments": {}})
    questions = iter(["check the Python version", "exit"])
    with (
        patch.object(main_module, "ask_question", side_effect=lambda: next(questions)),
        patch.object(main_module, "show_command_proposal"),
        patch.object(main_module, "execute_proposal") as execute,
        patch.object(main_module.typer, "confirm", return_value=False),
        patch.object(main_module.console, "print"),
    ):
        main_module.run_conversation(client)

    execute.assert_not_called()
    assert client.history_seen[0] == ("check the Python version", [])
    assert client.explanation_requests == []


def test_approved_command_output_is_only_shared_after_separate_consent():
    client = FakeClient({"action": "python_version", "arguments": {}})
    questions = iter(["check the Python version", "exit"])
    result = ExecutionResult(stdout="version output", stderr="", exit_code=0)
    with (
        patch.object(main_module, "ask_question", side_effect=lambda: next(questions)),
        patch.object(main_module, "show_command_proposal"),
        patch.object(main_module, "show_execution_result"),
        patch.object(main_module, "execute_proposal", return_value=result) as execute,
        patch.object(main_module.typer, "confirm", side_effect=[True, False]),
        patch.object(main_module.console, "print"),
    ):
        main_module.run_conversation(client)

    execute.assert_called_once()
    assert client.explanation_requests == []


def test_result_is_sent_for_explanation_only_after_output_consent():
    client = FakeClient({"action": "python_version", "arguments": {}})
    questions = iter(["check the Python version", "exit"])
    result = ExecutionResult(stdout="Python 3", stderr="", exit_code=0)
    with (
        patch.object(main_module, "ask_question", side_effect=lambda: next(questions)),
        patch.object(main_module, "show_command_proposal"),
        patch.object(main_module, "show_execution_result"),
        patch.object(main_module, "show_answer"),
        patch.object(main_module, "execute_proposal", return_value=result),
        patch.object(main_module.typer, "confirm", side_effect=[True, True]),
        patch.object(main_module.console, "status") as status,
        patch.object(main_module.console, "print"),
    ):
        status.return_value.__enter__.return_value = None
        main_module.run_conversation(client)

    assert len(client.explanation_requests) == 1
    assert "Python 3" in client.explanation_requests[0][0]
