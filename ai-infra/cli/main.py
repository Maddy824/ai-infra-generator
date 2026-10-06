"""CLI entry point for ai-infra."""

from __future__ import annotations

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


def _repo_arg() -> Path:
    return typer.Argument(
        ...,
        help="Path to the repository.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    )


def _check_target(target: str) -> None:
    from ai_infra.generator.generator import TARGETS

    if target not in TARGETS:
        console.print(f"[red]Invalid target '{target}'. Choose from: {', '.join(TARGETS)}[/red]")
        raise typer.Exit(1)


def _report_generated(files: list[Path], skipped: list[Path], target: str, repo: Path, done: bool = False) -> None:
    prefix = "Done! " if done else ""
    console.print(Panel(f"[green]{prefix}Generated {len(files)} file(s) for target '{target}'[/green]"))
    for f in files:
        console.print(f"  → {f.relative_to(repo)}")
    if skipped:
        console.print(
            f"[yellow]Skipped {len(skipped)} hand-edited file(s); re-run with --force to overwrite:[/yellow]"
        )
        for f in skipped:
            console.print(f"  [yellow]![/yellow] {f.relative_to(repo)}")


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
    repo: Path = _repo_arg(),
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
    repo: Path = _repo_arg(),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analyze a repository and produce analyzer_output.json."""
    _setup_logging(verbose)
    from ai_infra.analyzer.core import analyze as run_analyze

    result = run_analyze(repo)
    services = ", ".join(result["dependencies"]["inferred_services"]) or "none"
    console.print(Panel(
        f"[green]Analysis complete[/green]\n"
        f"Language: {result.get('language')}\n"
        f"Framework: {result.get('framework')}\n"
        f"Port: {result.get('detected_port')}\n"
        f"Inferred services: {services}"
    ))


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


@app.command()
def plan(
    repo: Path = _repo_arg(),
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
        raise typer.Exit(1) from None

    planner = Planner(repo)
    try:
        model = planner.plan(analyzer_output)
        console.print(Panel(f"[green]Plan complete![/green]\nProject: {model.project_name}\nServices: {len(model.services)}"))
    except RuntimeError as exc:
        console.print(f"[red]Planning failed: {exc}[/red]")
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@app.command()
def generate(
    repo: Path = _repo_arg(),
    target: str = typer.Option("compose", "--target", "-t", help="Generation target."),
    force: bool = typer.Option(False, "--force", "-f", help="Force regeneration."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Generate infrastructure files from the InfraModel."""
    _setup_logging(verbose)
    from ai_infra.generator.generator import Generator
    from ai_infra.state.state_manager import StateManager

    _check_target(target)

    state = StateManager(repo)
    try:
        model = state.read_infra_model()
    except FileNotFoundError:
        console.print("[red]No infra model. Run 'ai-infra plan' first.[/red]")
        raise typer.Exit(1) from None

    gen = Generator(repo)
    files = gen.generate(model, target=target, force=force)
    _report_generated(files, gen.skipped, target, repo)


# ---------------------------------------------------------------------------
# fix
# ---------------------------------------------------------------------------


@app.command()
def fix(
    repo: Path = _repo_arg(),
    logs: Path = typer.Option(..., "--logs", "-l", help="Path to log file.", exists=True, dir_okay=False),
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
        raise typer.Exit(1) from None

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
    repo: Path = _repo_arg(),
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

    # Validate up front so a typo doesn't cost an LLM call.
    _check_target(target)

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
        raise typer.Exit(1) from None
    console.print(f"  Project: {model.project_name}  Services: {len(model.services)}")

    # 4. Generate
    gen = Generator(repo)
    files = gen.generate(model, target=target, force=force)
    _report_generated(files, gen.skipped, target, repo, done=True)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    repo: Path = _repo_arg(),
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
        console.print(f"  [bold]Services:[/bold] {', '.join(s.name for s in model.services) or 'none'}")
        if model.services:
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

    # Show generated files that need attention
    tracked = state.get_state().get("files", {})
    if tracked:
        console.print()
        console.print(f"  [bold]Generated files:[/bold] {len(tracked)}")
    missing = [f for f in tracked if not (repo / f).is_file()]
    modified = [f for f in tracked if f not in missing and state.was_modified(f)]
    if modified:
        console.print(f"  [yellow]Modified since generation ({len(modified)}):[/yellow]")
        for f in modified:
            console.print(f"    {f}")
    if missing:
        console.print(f"  [red]Missing ({len(missing)}):[/red]")
        for f in missing:
            console.print(f"    {f}")


if __name__ == "__main__":
    app()
