"""Rich terminal digest summaries and details."""

from rich.console import Console
from rich.table import Table

from radar.digest.models import Digest


def render_terminal(digest: Digest, console: Console) -> None:
    """Print a compact ranking followed by actionable candidate details."""
    if not digest.items:
        console.print(f"[yellow]{digest.empty_message}[/]")
        return
    table = Table("#", "Score", "Confidence", "Opportunity", "Effort", "Merge")
    for item in digest.items:
        confidence = f"{item.confidence:.0%}"
        if item.low_confidence:
            confidence += " LOW"
        table.add_row(
            str(item.rank),
            f"{item.score:.1f}",
            confidence,
            f"{item.repository}#{item.number} — {item.title}",
            f"{item.effort_low_hours:g}-{item.effort_high_hours:g}h",
            f"{item.merge_band} ({item.merge_estimate:.0%})",
        )
    console.print(table)
    for item in digest.items:
        console.print(f"\n[bold]{item.rank}. {item.repository}#{item.number}[/] {item.url}")
        if item.low_confidence:
            console.print("[yellow]Low confidence: verify missing or uncertain evidence.[/]")
        console.print(f"First move: {item.suggested_first_move}")
