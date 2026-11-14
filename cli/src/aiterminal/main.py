"""Interactive AITerminal CLI."""

from __future__ import annotations

import typer

from .client import AITerminalClient, AITerminalError
from .terminal import ask_question, console, show_answer

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
                answer = client.ask(question, history)
        except AITerminalError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            continue

        show_answer(answer)
        history.extend(({"role": "user", "content": question}, {"role": "assistant", "content": answer}))
        del history[:-20]


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
