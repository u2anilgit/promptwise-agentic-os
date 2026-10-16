# scripts/promptwise.py
from pathlib import Path

import typer

import core.diagnostics.checks as diagnostics_checks
from core.diagnostics.hardware import detect_hardware, write_hardware_profile
from core.packs.loader import PackValidationError
from core.packs.registry import PackInstallError, install_pack, list_installed_packs, remove_pack

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


@app.command("pin-tools")
def pin_tools() -> None:
    """Pin the current MCP tool descriptions/schemas in tool_registry.yaml.
    Review the tool text first — a later change to it will be denied until re-pinned."""
    from core.config.resolve import resolve_config_auto
    from core.policy.tool_pins import write_pins
    from gateway.mcp_server import live_tool_specs

    pinned = write_pins(resolve_config_auto(), live_tool_specs())
    typer.echo(f"pinned {len(pinned)} tool(s): {', '.join(pinned) or 'none'}")


db_app = typer.Typer(help="Database schema management")
app.add_typer(db_app, name="db")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all pending Alembic migrations (creates the database if absent)."""
    from core.config.resolve import resolve_config_auto
    from core.db.migrate import migrate_to_head

    revision = migrate_to_head(resolve_config_auto())
    typer.echo(f"database at revision {revision}")


pack_app = typer.Typer(help="Manage installed packs (docs/ARCHITECTURE.md §3)")
app.add_typer(pack_app, name="pack")


@pack_app.command("list")
def pack_list() -> None:
    """List installed packs; invalid manifests are flagged, not hidden."""
    results = list_installed_packs()
    if not results:
        typer.echo("no packs installed")
        return
    for pack_dir, manifest, error in results:
        if manifest is not None:
            typer.echo(f"{manifest.name}@{manifest.version} ({manifest.kind}) — {pack_dir.name}")
        else:
            typer.echo(f"[INVALID] {pack_dir.name} — {error}")


@pack_app.command("install")
def pack_install(name: str) -> None:
    """Copy packs/registry/<name> into packs/installed/<name> after validation."""
    try:
        manifest = install_pack(name)
    except (PackInstallError, PackValidationError) as exc:
        typer.echo(f"install failed: {exc}")
        raise typer.Exit(code=1)
    typer.echo(f"installed {manifest.name}@{manifest.version}")


@pack_app.command("remove")
def pack_remove(name: str) -> None:
    """Delete packs/installed/<name>."""
    removed = remove_pack(name)
    if not removed:
        typer.echo(f"{name} is not installed")
        raise typer.Exit(code=1)
    typer.echo(f"removed {name}")


@app.command()
def support_bundle(out: Path = Path("support-bundle.zip")) -> None:
    """Generate a redacted support bundle for troubleshooting."""
    from core.config.resolve import resolve_config_auto
    from core.diagnostics.support_bundle import generate_support_bundle

    config = resolve_config_auto()
    result = generate_support_bundle(config, out)
    typer.echo(f"wrote {result}")


if __name__ == "__main__":
    app()
