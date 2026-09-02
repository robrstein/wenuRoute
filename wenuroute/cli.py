"""WenuRoute CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from wenuroute import __version__
from wenuroute.analyzer import Analyzer
from wenuroute.graph import render_console, render_html

console = Console()


@click.command()
@click.argument(
    "project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    metavar="PROJECT_DIR",
)
@click.option(
    "--output", "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output file path.  Defaults to <PROJECT_DIR>/wenuroute_graph.html",
)
@click.option(
    "--format", "-f",
    "fmt",
    type=click.Choice(["html", "text"], case_sensitive=False),
    default="html",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Print each file as it is parsed.",
)
@click.option(
    "--arch",
    is_flag=True,
    default=False,
    help="Generate the architecture digital-library HTML instead of the "
         "execution-route graph (component diagram, sequence diagrams, "
         "roadmap for data-flow/lifecycle/pipeline views).",
)
@click.version_option(__version__, prog_name="wenuroute")
def main(
    project: Path,
    output: Path | None,
    fmt: str,
    verbose: bool,
    arch: bool,
) -> None:
    """WenuRoute — visualise execution routes in your codebase.

    \b
    PROJECT_DIR  Root directory of the project to analyse (default: current dir).

    Examples:

    \b
      wenuroute ./my-app
      wenuroute ./my-app --format text
      wenuroute ./my-app -o report.html
      wenuroute ./my-app --arch
    """
    if arch and fmt == "text":
        console.print(
            "[red]Error:[/] --arch is only supported with HTML output "
            "(do not combine with --format text)."
        )
        sys.exit(1)

    project = project.resolve()
    console.print(f"[bold cyan]WenuRoute[/] v{__version__}")
    console.print(f"Analysing [green]{project}[/] …\n")

    messages: list[str] = []

    def _progress(msg: str) -> None:
        if verbose:
            console.print(f"  [dim]{msg}[/]")
        else:
            messages.append(msg)

    analyzer = Analyzer(project, progress_callback=_progress)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("Scanning files…", total=None)
        graph = analyzer.analyze()
        progress.update(task, description="Done.")

    console.print(
        f"Found [bold]{len(graph.nodes)}[/] nodes, [bold]{len(graph.edges)}[/] edges.\n"
    )

    if arch:
        from wenuroute.arch import render_arch_html
        from wenuroute.arch.manifest import scan_dependencies

        dependency_graph = scan_dependencies(project)
        out_path = output or (project / "wenuroute_arch.html")
        render_arch_html(graph, dependency_graph, out_path)
        console.print(f"[bold green]✓[/] Architecture library saved to [underline]{out_path}[/]")
        console.print("  Open it in your browser to explore the architecture views.")
    elif fmt == "html":
        out_path = output or (project / "wenuroute_graph.html")
        try:
            render_html(graph, out_path)
            console.print(f"[bold green]✓[/] Graph saved to [underline]{out_path}[/]")
            console.print("  Open it in your browser to explore the execution routes.")
        except ImportError as exc:
            console.print(f"[red]Error:[/] {exc}")
            sys.exit(1)
    else:
        text = render_console(graph)
        if output:
            output.write_text(text, encoding="utf-8")
            console.print(f"[bold green]✓[/] Report saved to [underline]{output}[/]")
        else:
            console.print(text)
