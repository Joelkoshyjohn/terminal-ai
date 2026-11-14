from unittest.mock import patch

from typer.testing import CliRunner

from aiterminal import main as main_module


class FakeClient:
    def __init__(self):
        self.history_seen = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def ask(self, question, history):
        self.history_seen.append((question, list(history)))
        return "answer"


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
