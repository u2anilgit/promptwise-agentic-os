from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from core.config.resolve import resolve_config_auto
from core.diagnostics.checks import run_diagnostics
from core.diagnostics.hardware import detect_hardware, write_hardware_profile
from core.routing.catalog import load_catalog
from core.routing.cost import CostRecord, cost_report
from core.routing.router import RouteRequest, RoutingDecision, route_request
from gateway.healthcheck import is_alive


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = Path(resolve_config_auto()["diagnostics"]["hardware_profile_path"])
    write_hardware_profile(detect_hardware(), path)
    yield


app = FastAPI(title="PromptWise Agentic OS Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok" if is_alive() else "down"}


@app.get("/diagnostics")
def diagnostics() -> list[dict[str, str]]:
    return [result.model_dump() for result in run_diagnostics()]


@app.post("/route", response_model=RoutingDecision)
def route(request: RouteRequest) -> RoutingDecision:
    return route_request(request)


@app.post("/cost-report")
def cost_report_endpoint(records: list[CostRecord]) -> dict:
    catalog = load_catalog()
    for record in records:
        if record.tier not in catalog:
            raise HTTPException(status_code=422, detail=f"unknown tier: {record.tier}")
    return cost_report(records, catalog)
