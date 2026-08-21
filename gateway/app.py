from fastapi import FastAPI

from core.diagnostics.checks import run_diagnostics
from gateway.healthcheck import is_alive

app = FastAPI(title="PromptWise Agentic OS Gateway", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok" if is_alive() else "down"}


@app.get("/diagnostics")
def diagnostics() -> list[dict[str, str]]:
    return [result.model_dump() for result in run_diagnostics()]
