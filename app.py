from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from data_loader import load_data
from agent import PropertyAssistant

console = Console()


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        console.print("[bold red]Missing OPENAI_API_KEY.[/bold red]")
        console.print("Create a .env file from .env.example and add your key.")
        raise SystemExit(1)

    data_dir = Path(__file__).parent / "data"
    console.print(Panel("Loading UrbanTrace sample data...", title="Startup"))
    store = load_data(data_dir)
    assistant = PropertyAssistant(store)

    console.print(Panel(
        "Ask natural-language questions about properties, owners, sales, and market stats.\n"
        "Try: Show me SRL-owned properties in Gheorgheni sold over 1,000,000 RON since 2024.\n"
        "Type [bold]exit[/bold] to quit.",
        title="UrbanTrace AI Search Assistant",
    ))

    while True:
        user_text = console.input("\n[bold cyan]You:[/bold cyan] ").strip()
        if user_text.lower() in {"exit", "quit", "q"}:
            console.print("Goodbye!")
            break
        if not user_text:
            continue

        try:
            answer = assistant.ask(user_text)
            console.print("\n[bold green]Assistant:[/bold green]")
            console.print(Markdown(answer))
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")


if __name__ == "__main__":
    main()
