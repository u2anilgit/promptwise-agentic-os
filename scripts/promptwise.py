# scripts/promptwise.py
from pathlib import Path

import typer

import core.diagnostics.checks as diagnostics_checks
from core.diagnostics.hardware import detect_hardware, write_hardware_profile

app = typer.Typer(help="PromptWise Agentic OS — operator CLI")

DEFAULT_PROFILE_PATH = Path("config/hardware_profile.yaml")


@app.command()
def doctor() -> None:
    """Run all health checks. Exit 0 unless any check FAILs."""
    results = diagnostics_checks.run_diagnostics()
    has_failure = False
    for result in results:
        typer.echo(f"[{result.status}] {result.name} — {result.message}")
        if result.status == "FAIL":
            has_failure = True
    if has_failure:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


@app.command()
def profile(out: Path = DEFAULT_PROFILE_PATH) -> None:
    """Detect hardware and write hardware_profile.yaml."""
    detected = detect_hardware()
    write_hardware_profile(detected, out)
    typer.echo(f"wrote {out} — {detected.total_ram_gb}GB total RAM, {detected.cpu_count} CPUs, GPU={detected.has_gpu}")


if __name__ == "__main__":
    app()
