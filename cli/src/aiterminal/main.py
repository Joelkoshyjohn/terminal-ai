"""Interactive AITerminal CLI."""

from __future__ import annotations

import typer

from .client import AITerminalClient, AITerminalError
from .executor import (
    CommandExecutionError,
    CommandProposal,
    CommandValidationError,
    describe_proposal,
    execute_proposal,
    output_for_ai,
)
from .terminal import ask_question, console, show_answer, show_command_proposal, show_execution_result

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def run_conversation(client: AITerminalClient) -> None:
    history: list[dict[str, str]] = []
    while True:
        try:
            question = ask_question().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            return
        command = question.lower()
        if command in {"exit", "quit"}:
            console.print("Goodbye!")
            return
        if command in {"clear", "/clear"}:
            history.clear()
            console.clear()
            console.print("[bold]AITerminal ready![/bold]")
            continue
        if not question:
            continue

        try:
            with console.status("Thinking...", spinner="dots"):
                response = client.ask_with_proposal(question, history)
        except AITerminalError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            continue

        history.extend(
            ({"role": "user", "content": question}, {"role": "assistant", "content": response.answer})
        )
        del history[:-20]
        if response.proposal is None:
            show_answer(response.answer)
            continue

        try:
            proposal = CommandProposal.from_payload(response.proposal)
            description = describe_proposal(proposal)
        except CommandValidationError as exc:
            show_answer(response.answer)
            console.print(f"[bold red]Local action rejected: {exc}[/bold red]")
            continue
        except CommandExecutionError as exc:
            show_answer(response.answer)
            console.print(f"[bold red]Local action unavailable: {exc}[/bold red]")
            continue

        show_command_proposal(response.answer, description)
        if not typer.confirm("Run this local action?", default=False):
            console.print("Local action canceled.")
            continue

        try:
            result = execute_proposal(proposal)
        except (CommandExecutionError, CommandValidationError) as exc:
            console.print(f"[bold red]Local execution failed: {exc}[/bold red]")
            continue

        show_execution_result(result)
        if typer.confirm(
            "Send the captured output to AITerminal Cloud for an AI explanation? "
            "Review it first; sensitive-looking values will be masked.",
            default=False,
        ):
            explanation_request = (
                "Explain this local command result. Do not propose or run another local command.\n\n"
                f"{output_for_ai(result)}"
            )
            try:
                with console.status("Asking AI to explain the result...", spinner="dots"):
                    explanation = client.ask(explanation_request, history)
            except AITerminalError as exc:
                console.print(f"[bold red]{exc}[/bold red]")
            else:
                show_answer(explanation)


@app.callback(invoke_without_command=True)
def main() -> None:
    """Ask questions of the AITerminal cloud service."""
    console.print("Connecting to AITerminal Cloud...")
    try:
        with AITerminalClient() as client:
            console.print("[bold]AITerminal ready![/bold]")
            run_conversation(client)
    except KeyboardInterrupt:
        console.print("\nGoodbye!")
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
