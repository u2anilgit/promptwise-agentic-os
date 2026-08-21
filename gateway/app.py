from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from core.config.resolve import resolve_config
from core.diagnostics.checks import run_diagnostics
from core.diagnostics.hardware import detect_hardware, write_hardware_profile
from gateway.healthcheck import is_alive


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = Path(resolve_config()["diagnostics"]["hardware_profile_path"])
    write_hardware_profile(detect_hardware(), path)
    yield


app = FastAPI(title="PromptWise Agentic OS Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok" if is_alive() else "down"}


@app.get("/diagnostics")
def diagnostics() -> list[dict[str, str]]:
    return [result.model_dump() for result in run_diagnostics()]
