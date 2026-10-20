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


dashboard_app = typer.Typer(help="Dashboard access")
app.add_typer(dashboard_app, name="dashboard")


@dashboard_app.command("token")
def dashboard_token() -> None:
    """Print the gateway's API bearer token (created on first use). Replace the file to rotate it."""
    from gateway.auth import load_or_create_token, token_path
    from gateway.mcp_guard import operator_config

    from gateway.auth import CredentialUnavailable

    op = operator_config()
    try:
        value = load_or_create_token(op)
    except CredentialUnavailable as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)
    typer.echo(f"# {token_path(op)}")
    typer.echo(value)


usage_app = typer.Typer(help="Agent-reported model usage and cost per completed task")
app.add_typer(usage_app, name="usage")


@usage_app.command("record")
def usage_record(
    tier: str = typer.Option(..., help="Catalog tier name"),
    tokens_in: int = typer.Option(..., help="Input tokens"),
    tokens_out: int = typer.Option(..., help="Output tokens"),
    agent: str = typer.Option("cli", help="Reporting agent"),
    task_ref: str = typer.Option("", help="Task identifier (enables cost per task)"),
    spec_id: str = typer.Option("", help="Spec this belongs to"),
) -> None:
    """Record token usage (self-reported). Cost is fixed from the catalog tier at this moment."""
    from core.routing.usage import record_usage
    from gateway.mcp_guard import operator_config, pinned_config

    try:
        event = record_usage(
            tier, tokens_in, tokens_out, agent=agent, task_ref=task_ref or None, spec_id=spec_id or None,
            config=pinned_config(operator_config()),
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=2)
    typer.echo(f"recorded #{event.id}: {event.tier} {event.tokens_in}/{event.tokens_out} tokens, ${event.cost_usd}")


@usage_app.command("report")
def usage_report_cmd(days: int = typer.Option(7, help="Window in days (1-365)")) -> None:
    """Totals, by tier and by agent, and cost per completed task over the window."""
    from core.routing.usage import usage_report
    from gateway.mcp_guard import operator_config, pinned_config

    try:
        report = usage_report(days=days, config=pinned_config(operator_config()))
    except ValueError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=2)
    typer.echo(f"last {report.days} day(s): events {report.events}, tasks {report.tasks}, total ${report.total_cost_usd}")
    per_task = "n/a (no task references)" if report.cost_per_task_usd is None else f"${report.cost_per_task_usd}"
    typer.echo(f"cost per referenced task: {per_task}")
    for name, bucket in sorted(report.by_tier.items()):
        typer.echo(f"  tier {name}: {bucket.events} events, ${bucket.cost_usd}")
    for name, bucket in sorted(report.by_agent.items()):
        typer.echo(f"  agent {name}: {bucket.events} events, ${bucket.cost_usd}")


@app.command("ingest")
def ingest(
    root: Path = typer.Argument(Path("."), help="Project to refresh"),
    session_file: list[Path] = typer.Option([], "--session-file", help="Text file to record as session facts (repeat)"),
    session_id: str = typer.Option(None, help="Session the facts belong to"),
) -> None:
    """One ingestion sweep: refresh the code index and record session text as facts. Run it from a
    scheduler (cron, systemd timer, Task Scheduler); see docs/MAINTENANCE.md. Exit 1 if any step failed."""
    from core.ingestion import sweep

    texts = [f.read_text(encoding="utf-8") for f in session_file]
    result = sweep.run_ingestion_sweep(root.resolve(), session_texts=texts or None, session_id=session_id)
    typer.echo(f"{result.root}: code index {'refreshed' if result.code_index_refreshed else 'NOT refreshed'}, "
               f"facts recorded {result.facts_recorded}, failed {result.facts_failed}")
    for error in result.errors:
        typer.echo(f"  error: {error}")
    if result.errors:
        raise typer.Exit(code=1)


spec_app = typer.Typer(help="Spec-driven workflow: specify -> plan -> tasks -> complete -> verify")
app.add_typer(spec_app, name="spec")

_SPEC_TASK_KEYS = {"id", "requirement_ids", "depends_on", "expected_symbols", "task_type"}


def _spec_run(action):
    """Run a spec verb; a ValueError (stage order, bad input, bad JSON) or OSError is a one-line error, exit 2."""
    try:
        return action()
    except (ValueError, OSError) as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=2)


def _load_json_list(path: Path) -> list[dict]:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError(f"{path} must contain a JSON list of objects")
    return data


@spec_app.command("specify")
def spec_specify(
    request: str,
    requirement: list[str] = typer.Option(..., "--requirement", "-r", help="One requirement sentence (repeat for several)"),
    complexity: str = typer.Option("standard", help="standard or trivial (one requirement only)"),
) -> None:
    """Record a feature request and its requirements (numbered R1, R2, ...)."""
    from core.spec import engine

    result = _spec_run(lambda: engine.specify_feature(request, list(requirement), complexity=complexity))  # type: ignore[arg-type]
    typer.echo(f"spec_id {result.spec_id}")
    for req in result.requirements:
        typer.echo(f"{req.id}: {req.text}")
    for violation in result.violations:
        typer.echo(f"warning: EARS {violation.requirement_id}: {violation.reason}")


@spec_app.command("plan")
def spec_plan(spec_id: str, approach: str) -> None:
    """Record the implementation approach."""
    from core.spec import engine

    _spec_run(lambda: engine.plan_feature(spec_id, approach))
    typer.echo(f"planned {spec_id}")


@spec_app.command("tasks")
def spec_tasks(
    spec_id: str,
    tasks: Path = typer.Option(..., help="JSON list: [{id, requirement_ids, depends_on?, expected_symbols?, task_type?}]"),
    checks: Path = typer.Option(..., help="JSON list: [{requirement_id, command, files: [...]}]"),
) -> None:
    """Break the plan into tasks and freeze one acceptance check per requirement."""
    from core.spec import engine
    from core.spec.models import AcceptanceCheck, TaskNode

    def action():
        raw_tasks = _load_json_list(tasks)
        for raw in raw_tasks:
            unknown = set(raw) - _SPEC_TASK_KEYS
            if unknown:
                raise ValueError(f"task '{raw.get('id', '?')}' has unsupported keys {sorted(unknown)}")
        return engine.tasks_feature(
            spec_id, [TaskNode(**raw) for raw in raw_tasks], [AcceptanceCheck(**raw) for raw in _load_json_list(checks)]
        )

    result = _spec_run(action)
    typer.echo(f"frozen {len(result.frozen)} acceptance check(s); stage tasked")


@spec_app.command("complete")
def spec_complete(spec_id: str, task_id: str, evidence: str = typer.Option(..., help="What was done"), cwd: Path | None = None) -> None:
    """Claim a task is done; accepted only through the frozen, grounded gate."""
    from core.spec import engine

    result = _spec_run(lambda: engine.complete_task(spec_id, task_id, evidence, cwd=cwd))
    if result.accepted:
        grounded = "grounded" if result.verify and result.verify.grounded else "ungrounded (allowed by config)"
        layers = [name for name, on in result.independence.items() if on]
        typer.echo(f"accepted task {task_id} ({grounded}; independent layers: {', '.join(layers) or 'none'})")
        return
    typer.echo(f"rejected task {task_id}: {', '.join(result.reasons)}")
    for note in result.notes:
        typer.echo(f"  reviewer: {note}")
    raise typer.Exit(code=1)


@spec_app.command("verify")
def spec_verify(spec_id: str) -> None:
    """Exit 0 only if every task is done and every requirement is covered."""
    from core.spec import engine

    result = _spec_run(lambda: engine.verify_feature(spec_id))
    if result.verified:
        typer.echo(f"verified {spec_id}")
        return
    typer.echo(f"not verified: outstanding {result.outstanding}, uncovered requirements {result.uncovered_requirements}")
    raise typer.Exit(code=1)


@spec_app.command("converge")
def spec_converge(spec_id: str) -> None:
    """Read-only drift report; exit 1 if the spec is stale."""
    from core.spec import engine

    report = _spec_run(lambda: engine.converge_feature(spec_id))
    if report.stale:
        typer.echo(f"stale: {', '.join(report.reasons)}")
        raise typer.Exit(code=1)
    typer.echo(f"not stale ({report.done_tasks}/{report.planned_tasks} tasks done)")


@spec_app.command("status")
def spec_status_cmd(spec_id: str) -> None:
    """Show stage, requirements and task statuses."""
    from core.spec import engine

    status = _spec_run(lambda: engine.spec_status(spec_id))
    typer.echo(f"spec {status.spec_id}: {status.request}")
    typer.echo(f"stage: {status.stage} ({status.complexity})")
    for req in status.requirements:
        typer.echo(f"  {req.id}: {req.text}")
    for check in status.checks:
        typer.echo(f"  check {check.requirement_id}: baseline {check.baseline} (expect {check.expect_baseline})")
    for task in status.tasks:
        suffix = f" - {task.error}" if task.error else ""
        typer.echo(f"  task {task.task_id}: {task.status} (covers {', '.join(task.requirement_ids)}){suffix}")


@spec_app.command("amend")
def spec_amend(
    spec_id: str,
    requirement_id: str,
    command: str = typer.Option(...),
    file: list[str] = typer.Option(..., "--file", help="File the check depends on (repeat)"),
    reason: str = typer.Option(..., help="Why the check is changing (audited)"),
    expect_baseline: str = typer.Option("fail", help="fail: the new check must fail now; pass: explicit regression guard"),
) -> None:
    """Deliberately replace a frozen acceptance check; tasks that relied on it are reopened."""
    from core.spec import engine
    from core.spec.models import AcceptanceCheck

    def action():
        before = {t.task_id: t.status for t in engine.spec_status(spec_id).tasks}
        engine.amend_check(spec_id, requirement_id, AcceptanceCheck(requirement_id=requirement_id, command=command, files=list(file), expect_baseline=expect_baseline), reason=reason, require_grant=False)  # type: ignore[arg-type]
        after = {t.task_id: t.status for t in engine.spec_status(spec_id).tasks}
        return [tid for tid, was in before.items() if was == "done" and after.get(tid) == "pending"]

    reopened = _spec_run(action)
    typer.echo(f"amended {requirement_id} of {spec_id}; reopened: {', '.join(reopened) or 'none'}")


@spec_app.command("allow-amend")
def spec_allow_amend(
    spec_id: str,
    ttl: int = typer.Option(900, min=30, max=86400, help="Seconds the grant stays valid"),
) -> None:
    """Let an agent replace ONE frozen check of this spec (amend_check over MCP), within --ttl seconds."""
    from core.audit.log import record_audit
    from core.policy.jit import grant_jit_permission
    from core.spec import engine
    from gateway.mcp_guard import operator_config, pinned_config

    def action():
        # The gateway's view of state (operator config, governance paths pinned), so the grant lands
        # where the MCP amend_check looks for it, even when the operator file moves it out of the project.
        config = pinned_config(operator_config())
        engine.spec_status(spec_id, config=config)  # unknown spec -> error, no grant
        grant = grant_jit_permission(config, engine.amend_grant_scope(spec_id), ttl)
        record_audit(config, actor="cli", action="jit_grant", target=grant.scope, result="allow", detail={"expires_at": grant.expires_at})
        return grant

    grant = _spec_run(action)
    typer.echo(f"one amend of {spec_id} allowed until {grant.expires_at}")


mcp_cli = typer.Typer(help="Inspect the MCP tool surface")
app.add_typer(mcp_cli, name="mcp")


@mcp_cli.command("tools")
def mcp_tools() -> None:
    """List every live MCP tool with its registry/pin status (read-only, no audit writes)."""
    from core.config.resolve import resolve_config_auto
    from core.policy.tool_pins import tool_description_hash
    from core.policy.tool_registry import load_tool_registry
    from gateway.mcp_server import live_tool_specs

    registry = load_tool_registry(resolve_config_auto())
    for name, (description, schema) in live_tool_specs().items():
        entry = registry.get(name)
        if entry is None:
            status = "UNREGISTERED"
        elif not entry.enabled:
            status = "DISABLED"
        elif entry.description_sha256 is None:
            status = "UNPINNED"
        elif entry.description_sha256 != tool_description_hash(description, schema):
            status = "MISMATCH (re-pin with `promptwise pin-tools`)"
        else:
            status = "pinned"
        typer.echo(f"{name} - {status}")


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
