from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.main import app

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs" / "interface_contract.md"
AUTO_ROUTES = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}


def test_interface_contract_documents_every_route() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    missing: list[str] = []

    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None or path in AUTO_ROUTES:
            continue
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                marker = f"| {method} | `{path}` |"
                if marker not in contract:
                    missing.append(marker)
        elif isinstance(route, WebSocketRoute):
            marker = f"| WebSocket | `{path}` |"
            if marker not in contract:
                missing.append(marker)

    assert missing == []
