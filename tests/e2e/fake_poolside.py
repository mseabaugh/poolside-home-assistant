"""Synthetic Poolside HTTP/WebSocket service for isolated end-to-end tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from aiohttp import WSMsgType, web

SYNTHETIC_TOKEN = "synthetic-token"
_FIXTURES = Path(__file__).parents[1] / "fixtures"


def _fixture(name: str) -> dict[str, Any]:
    """Load a synthetic fixture for each isolated service instance."""
    return cast("dict[str, Any]", json.loads((_FIXTURES / name).read_text()))


class FakePoolsideService:
    """Stateful fake that implements only the confirmed application boundary."""

    def __init__(self) -> None:
        """Initialize isolated state and request history."""
        self.config = _fixture("user_config.json")
        self.states = _fixture("states.json")
        self.desired = _fixture("desired.json")
        self.requests: list[dict[str, Any]] = []
        self.websockets: set[web.WebSocketResponse] = set()

    def application(self) -> web.Application:
        """Build an aiohttp application without global mutable state."""
        application = web.Application()
        application.add_routes(
            [
                web.get("/health", self.health),
                web.get("/test/state", self.browser_state),
                web.post("/api/jsonrpc/v1", self.rpc),
                web.get("/websocket", self.websocket),
            ]
        )
        return application

    async def health(self, _request: web.Request) -> web.Response:
        """Expose container health without authentication or internal data."""
        return web.json_response({"status": "ok"})

    async def browser_state(self, _request: web.Request) -> web.Response:
        """Expose synthetic state for browser assertions in the isolated test network."""
        return web.json_response({"desired": self.desired})

    @staticmethod
    def _authorized(request: web.Request) -> bool:
        """Require the synthetic credential on application endpoints."""
        return request.headers.get("Authorization") == f"Bearer {SYNTHETIC_TOKEN}"

    async def rpc(self, request: web.Request) -> web.Response:
        """Handle confirmed JSON-RPC calls and mutate only synthetic Controls."""
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid_json"}, status=400)
        self.requests.append(deepcopy(payload))
        method = payload.get("method")
        params = payload.get("params", {})
        result: Any
        if method == "ping":
            result = True
        elif method == "User.getConfig":
            result = self.config
        elif method == "Site.getStates":
            result = self.states
        elif method == "Site.getDesiredState":
            result = self.desired
        elif method == "Site.setDesiredState2":
            records = params.get("DesiredStates", [])
            self._merge_desired(records)
            await self._broadcast("Site.setDesiredState", {"changed": True})
            result = True
        elif method == "Site.setTheme" and params.get("Status") == "ON":
            self._activate_theme(params.get("UUID"))
            await self._broadcast("Device.setConfig", {"changed": True})
            result = True
        else:
            return web.json_response(
                {
                    "error": {"code": -32601, "message": "method_not_found"},
                    "id": payload.get("id"),
                    "jsonrpc": "2.0",
                }
            )
        return web.json_response(
            {
                "id": payload.get("id"),
                "jsonrpc": "2.0",
                "result": result,
                "traceId": payload.get("traceId"),
            }
        )

    def _merge_desired(self, records: Any) -> None:
        """Merge synthetic desired records by Control UUID."""
        if not isinstance(records, list):
            return
        indexed = {
            row.get("ControlUUID"): row
            for row in self.desired["DesiredStates"]
            if isinstance(row, dict)
        }
        for record in records:
            if isinstance(record, dict) and record.get("ControlUUID") in indexed:
                indexed[record["ControlUUID"]].update(deepcopy(record))

    def _activate_theme(self, theme_uuid: Any) -> None:
        """Mark exactly one synthetic Theme active."""
        for theme in self.config["Sites"][0]["Themes"]:
            theme["isWorking"] = theme.get("UUID") == theme_uuid

    async def websocket(self, request: web.Request) -> web.StreamResponse:
        """Open an authenticated push channel."""
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)
        self.websockets.add(websocket)
        await websocket.send_json({"method": "Connection.activate", "params": {}})
        try:
            async for message in websocket:
                if message.type is WSMsgType.ERROR:
                    break
        finally:
            self.websockets.discard(websocket)
        return websocket

    async def _broadcast(self, method: str, params: dict[str, Any]) -> None:
        """Push a synthetic update to every currently connected client."""
        for websocket in tuple(self.websockets):
            await websocket.send_json({"method": method, "params": params})


def main() -> None:
    """Run the synthetic service for Docker development and browser E2E."""
    web.run_app(FakePoolsideService().application(), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
