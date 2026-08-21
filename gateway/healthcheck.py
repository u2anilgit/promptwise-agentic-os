"""Fast liveness check — backs docker-compose's healthcheck directive.
Deliberately shallow (<200ms budget): no deep dependency checks here.
Deep checks live in core.diagnostics.checks.run_diagnostics, exposed at /diagnostics.
"""


def is_alive() -> bool:
    return True
