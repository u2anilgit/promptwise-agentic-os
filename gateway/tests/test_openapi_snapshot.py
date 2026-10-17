import json
from pathlib import Path

from gateway.app import app

SNAPSHOT = Path(__file__).resolve().parents[2] / "dashboard" / "openapi.json"


def test_committed_openapi_snapshot_matches_the_live_schema():
    """The dashboard's TypeScript types are generated from this file. If the API changes, regenerate it
    with `python -m scripts.export_openapi` and then `npm run gen:api` in dashboard/."""
    assert SNAPSHOT.exists(), "run: python -m scripts.export_openapi"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(app.openapi()))
