"""CLI entry point for ai-infra."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(
    name="ai-infra",
    help="AI Infrastructure Generator — analyze repos and generate Docker, K8s, Helm, Terraform, CI/CD, and monitoring configs.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s — %(message)s",
    )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Initialize the .ai-infra state directory."""
    _setup_logging(verbose)
    from ai_infra.state.state_manager import StateManager

    state = StateManager(repo)
    if state.exists():
        console.print("[yellow]State directory already exists.[/yellow]")
        return

    state.init_state_dir()
    state.write_hints_starter()
    console.print(Panel(f"[green]Initialized .ai-infra/ in {repo}[/green]"))


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


@app.command()
def analyze(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analyze a repository and produce analyzer_output.json."""
    _setup_logging(verbose)
    from ai_infra.analyzer.core import analyze as run_analyze

    result = run_analyze(repo)
    console.print(Panel(f"[green]Analysis complete[/green]\nLanguage: {result.get('language')}\nFramework: {result.get('framework')}"))


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


@app.command()
def plan(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the AI planner to produce an InfraModel."""
    _setup_logging(verbose)
    from ai_infra.planner.planner import Planner
    from ai_infra.state.state_manager import StateManager

    state = StateManager(repo)
    if not state.exists():
        console.print("[red]No .ai-infra/ directory. Run 'ai-infra init' first.[/red]")
        raise typer.Exit(1)

    try:
        analyzer_output = state.read_analyzer_output()
    except FileNotFoundError:
        console.print("[red]No analyzer output. Run 'ai-infra analyze' first.[/red]")
        raise typer.Exit(1)

    planner = Planner(repo)
    try:
        model = planner.plan(analyzer_output)
        console.print(Panel(f"[green]Plan complete![/green]\nProject: {model.project_name}\nServices: {len(model.services)}"))
    except RuntimeError as exc:
        console.print(f"[red]Planning failed: {exc}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@app.command()
def generate(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    target: str = typer.Option("compose", "--target", "-t", help="Generation target."),
    force: bool = typer.Option(False, "--force", "-f", help="Force regeneration."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Generate infrastructure files from the InfraModel."""
    _setup_logging(verbose)
    from ai_infra.generator.generator import Generator
    from ai_infra.state.state_manager import StateManager

    valid_targets = {"compose", "k8s", "ci", "helm", "iac", "monitoring", "tenancy", "all"}
    if target not in valid_targets:
        console.print(f"[red]Invalid target '{target}'. Choose from: {', '.join(sorted(valid_targets))}[/red]")
        raise typer.Exit(1)

    state = StateManager(repo)
    try:
        model = state.read_infra_model()
    except FileNotFoundError:
        console.print("[red]No infra model. Run 'ai-infra plan' first.[/red]")
        raise typer.Exit(1)

    gen = Generator(repo)
    files = gen.generate(model, target=target, force=force)
    console.print(Panel(f"[green]Generated {len(files)} file(s) for target '{target}'[/green]"))
    for f in files:
        console.print(f"  → {f}")


# ---------------------------------------------------------------------------
# fix
# ---------------------------------------------------------------------------


@app.command()
def fix(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    logs: Path = typer.Option(..., "--logs", "-l", help="Path to log file."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Parse deployment logs and propose/apply fixes to the InfraModel."""
    _setup_logging(verbose)
    from ai_infra.fix.fix_loop import FixLoop

    loop = FixLoop(repo)
    try:
        result = loop.fix(logs, dry_run=dry_run)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    n_errors = len(result.get("errors", []))
    n_changes = len(result.get("changes", []))
    n_files = len(result.get("files", []))

    if dry_run:
        console.print(Panel(f"[yellow]Dry run:[/yellow] {n_errors} error(s), {n_changes} proposed change(s)"))
    else:
        console.print(Panel(f"[green]Fixed:[/green] {n_errors} error(s), {n_changes} change(s), {n_files} file(s) regenerated"))

    for change in result.get("changes", []):
        console.print(f"  {change}")


# ---------------------------------------------------------------------------
# run (full pipeline)
# ---------------------------------------------------------------------------


@app.command()
def run(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    target: str = typer.Option("all", "--target", "-t", help="Generation target."),
    force: bool = typer.Option(False, "--force", "-f", help="Force regeneration."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the full pipeline: init -> analyze -> plan -> generate."""
    _setup_logging(verbose)
    from ai_infra.analyzer.core import analyze as run_analyze
    from ai_infra.generator.generator import Generator
    from ai_infra.planner.planner import Planner
    from ai_infra.state.state_manager import StateManager

    # 1. Init
    state = StateManager(repo)
    if not state.exists():
        state.init_state_dir()
        state.write_hints_starter()
        console.print("[green]Initialized .ai-infra/[/green]")
    else:
        console.print("[dim]State directory already exists, reusing.[/dim]")

    # 2. Analyze
    console.print("[bold]Analyzing repository...[/bold]")
    result = run_analyze(repo)
    console.print(f"  Language: {result.get('language')}  Framework: {result.get('framework')}")

    # 3. Plan
    console.print("[bold]Running AI planner...[/bold]")
    planner = Planner(repo)
    try:
        model = planner.plan(result)
    except RuntimeError as exc:
        console.print(f"[red]Planning failed: {exc}[/red]")
        raise typer.Exit(1)
    console.print(f"  Project: {model.project_name}  Services: {len(model.services)}")

    # 4. Generate
    valid_targets = {"compose", "k8s", "ci", "helm", "iac", "monitoring", "tenancy", "all"}
    if target not in valid_targets:
        console.print(f"[red]Invalid target '{target}'. Choose from: {', '.join(sorted(valid_targets))}[/red]")
        raise typer.Exit(1)

    gen = Generator(repo)
    files = gen.generate(model, target=target, force=force)
    console.print(Panel(f"[green]Done! Generated {len(files)} file(s) for target '{target}'[/green]"))
    for f in files:
        console.print(f"  → {f}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    repo: Path = typer.Argument(..., help="Path to the repository."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Show the current state of the ai-infra pipeline."""
    _setup_logging(verbose)
    from ai_infra.state.state_manager import StateManager

    state = StateManager(repo)
    if not state.exists():
        console.print("[red]No .ai-infra/ directory found. Run 'ai-infra init' first.[/red]")
        raise typer.Exit(1)

    console.print(Panel("[bold]ai-infra pipeline status[/bold]"))

    # Check each artifact
    artifacts = [
        ("state.json", "State tracking"),
        ("analyzer_output.json", "Analyzer output"),
        ("infra_model.v1.json", "Infrastructure model"),
        ("plan.md", "Plan summary"),
        ("hints.yaml", "User hints"),
    ]
    for filename, label in artifacts:
        path = state.state_dir / filename
        if path.exists():
            size = path.stat().st_size
            console.print(f"  [green]✓[/green] {label:<25} ({filename}, {size:,} bytes)")
        else:
            console.print(f"  [dim]✗[/dim] {label:<25} ({filename})")

    # Show model summary if available
    try:
        model = state.read_infra_model()
        console.print()
        console.print(f"  [bold]Project:[/bold] {model.project_name}")
        console.print(f"  [bold]Services:[/bold] {', '.join(s.name for s in model.services)}")
        console.print(f"  [bold]Scale:[/bold] {model.services[0].sizing.scale}")
        enabled = []
        if model.helm.enabled:
            enabled.append("Helm")
        if model.iac.enabled:
            enabled.append(f"IaC ({model.iac.cloud_provider})")
        if model.monitoring.enabled:
            enabled.append("Monitoring")
        if model.multi_tenancy.enabled:
            enabled.append("Multi-tenancy")
        if enabled:
            console.print(f"  [bold]Enabled:[/bold] {', '.join(enabled)}")
        else:
            console.print("  [bold]Enabled:[/bold] Core only (compose, k8s, ci)")
    except FileNotFoundError:
        pass

    # Show dirty files
    st = state.get_state()
    dirty = [f for f, info in st.get("files", {}).items() if info.get("dirty", True)]
    if dirty:
        console.print()
        console.print(f"  [yellow]Dirty files ({len(dirty)}):[/yellow]")
        for f in dirty:
            console.print(f"    {f}")


if __name__ == "__main__":
    app()
