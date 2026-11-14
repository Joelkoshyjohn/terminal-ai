"""Small Rich helpers for the interactive terminal."""

from rich.console import Console
from rich.markdown import Markdown

console = Console()


def ask_question() -> str:
    return console.input("[bold cyan]You> [/bold cyan]")


def show_answer(answer: str) -> None:
    console.print("[bold green]AI>[/bold green]")
    console.print(Markdown(answer))
