"""Small Rich helpers for the interactive terminal."""

from rich.console import Console
from rich.markdown import Markdown

from .executor import ExecutionResult

console = Console()


def ask_question() -> str:
    return console.input("[bold cyan]You> [/bold cyan]")


def show_answer(answer: str) -> None:
    console.print("[bold green]AI>[/bold green]")
    console.print(Markdown(answer))


def show_command_proposal(answer: str, description: str) -> None:
    show_answer(answer)
    console.print("[bold yellow]Proposed local action[/bold yellow]")
    console.print(description, markup=False)


def show_execution_result(result: ExecutionResult) -> None:
    if result.timed_out:
        console.print("[bold red]Execution timed out.[/bold red]")
    console.print(f"Exit code: {result.exit_code}", markup=False)
    if result.stdout:
        console.print("[bold]stdout[/bold]")
        console.print(result.stdout, markup=False)
    if result.stderr:
        console.print("[bold]stderr[/bold]")
        console.print(result.stderr, markup=False)
