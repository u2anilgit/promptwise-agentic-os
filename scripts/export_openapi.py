"""Write the gateway's OpenAPI schema to dashboard/openapi.json (the dashboard's typed-client source)."""
import json
from pathlib import Path

from gateway.app import app

TARGET = Path(__file__).resolve().parents[1] / "dashboard" / "openapi.json"


def main() -> None:
    TARGET.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
