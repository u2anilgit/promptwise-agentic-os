# gateway/app.py
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config.resolve import resolve_config_auto
from core.diagnostics.checks import run_diagnostics
from core.diagnostics.hardware import detect_hardware, write_hardware_profile
from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, cost_report
from core.routing.router import RouteRequest, RoutingDecision, route_request
from core.verify.gate import verify_output
from core.verify.models import VerifyResult
from gateway.api.v1 import router as api_v1
from gateway.auth import require_token
from gateway.healthcheck import is_alive
from gateway.mcp_guard import operator_config

INSTALL_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = Path(resolve_config_auto()["diagnostics"]["hardware_profile_path"])
    write_hardware_profile(detect_hardware(), path)
    yield


SECURED = [Depends(require_token)]
routes = APIRouter()


@routes.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok" if is_alive() else "down"}


@routes.get("/diagnostics", dependencies=SECURED)
def diagnostics() -> list[dict[str, str]]:
    return [result.model_dump() for result in run_diagnostics()]


@routes.post("/route", dependencies=SECURED, response_model=RoutingDecision)
def route(request: RouteRequest) -> RoutingDecision:
    return route_request(request)


@routes.post("/cost-report", dependencies=SECURED)
def cost_report_endpoint(records: list[CostRecord]) -> dict:
    catalog = load_catalog()
    for record in records:
        if record.tier not in catalog:
            raise HTTPException(status_code=422, detail=f"unknown tier: {record.tier}")
    return cost_report(records, catalog)


class VerifyRequest(BaseModel):
    diff: str
    spec: str | None = None
    cwd: str | None = None
    ledger_key: str | None = None


@routes.post("/verify", dependencies=SECURED, response_model=VerifyResult)
def verify(request: VerifyRequest) -> VerifyResult:
    cwd = Path(request.cwd) if request.cwd else None
    return verify_output(diff=request.diff, spec=request.spec, cwd=cwd, ledger_key=request.ledger_key)


DASHBOARD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class DashboardFiles(StaticFiles):
    """The built dashboard bundle, served with a strict CSP. Nothing here is dynamic or privileged:
    the bundle only ever talks to the authenticated /api/v1 routes."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Content-Security-Policy"] = DASHBOARD_CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if path.replace("\\", "/").startswith("assets/") else "no-store"
        )
        return response


def create_app(dashboard_dir: Path | str | None = None) -> FastAPI:
    # No public schema or interactive docs: the schema is served behind the credential below, and the
    # Swagger/ReDoc pages would need third-party scripts the dashboard CSP does not allow anyway.
    application = FastAPI(
        title="PromptWise Agentic OS Gateway",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    @application.get("/openapi.json", dependencies=SECURED, include_in_schema=False)
    def openapi_schema() -> dict:
        return application.openapi()

    application.include_router(api_v1)
    application.include_router(routes)
    if dashboard_dir is None:
        # Operator config only (never the cwd's project layers) and resolved against the install, not the cwd:
        # the gateway's working directory may be a project an agent can edit, and this folder is served on the API's origin.
        dashboard_dir = operator_config().get("gateway", {}).get("dashboard_dir") or "dashboard/dist"
    bundle = Path(dashboard_dir)
    if not bundle.is_absolute():
        bundle = INSTALL_ROOT / bundle
    if (bundle / "index.html").is_file():  # mounted last so every API route wins
        application.mount("/", DashboardFiles(directory=bundle, html=True), name="dashboard")
    return application


app = create_app()
