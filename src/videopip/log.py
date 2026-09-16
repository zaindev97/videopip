from rich.console import Console

console = Console(highlight=False)


def step(msg: str) -> None:
    console.print(f"[bold cyan]>>[/bold cyan] {msg}")


def info(msg: str) -> None:
    console.print(f"   {msg}")


def warn(msg: str) -> None:
    console.print(f"   [yellow]! {msg}[/yellow]")


def ok(msg: str) -> None:
    console.print(f"   [green]OK[/green] {msg}")
