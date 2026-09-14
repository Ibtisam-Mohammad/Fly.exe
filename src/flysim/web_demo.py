# SPDX-License-Identifier: GPL-2.0-or-later
"""HTTP/WebSocket presentation service for the interactive multi-fly arena."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from flysim.errors import ConfigurationError, FlySimError, ReadinessError
from flysim.multifly_live import (
    InteractiveMultiFlyRuntime,
    build_full_cns_runtime,
    build_preview_runtime,
)

RuntimeFactory = Callable[[], InteractiveMultiFlyRuntime]
ALLOWED_CLIENT_COMMANDS = frozenset(
    {"start", "pause", "step", "reset", "place-stimulus", "remove-stimulus"}
)


class LiveDemoService:
    """Own one runtime and an optional wall-clock stepping thread."""

    def __init__(self, runtime_factory: RuntimeFactory) -> None:
        self._factory = runtime_factory
        self._runtime = runtime_factory()
        self._running = False
        self._closed = False
        self._step_count = 0
        self._last_error: str | None = None
        self._wall_started = time.perf_counter()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            name="flysim-live-demo",
            daemon=True,
        )
        self._thread.start()

    def _worker(self) -> None:
        while not self._closed:
            if not self._running:
                self._wake.wait(timeout=0.25)
                self._wake.clear()
                continue
            started = time.perf_counter()
            try:
                with self._lock:
                    self._runtime.step()
                    self._step_count += 1
            except Exception as exc:  # the service must expose and stop on runtime failure
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._running = False
                continue
            elapsed = time.perf_counter() - started
            biological_interval = self._runtime.coordinator.coupling_us / 1_000_000.0
            if elapsed < biological_interval:
                self._wake.wait(timeout=biological_interval - elapsed)
                self._wake.clear()

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._running = True
            self._last_error = None
            self._wake.set()
            return self.snapshot()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            return self.snapshot()

    def step_once(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                raise ConfigurationError("Pause the live demo before requesting one step")
            value = self._runtime.step()
            self._step_count += 1
            return self._decorate(value)

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            self._runtime.close()
            self._runtime = self._factory()
            self._step_count = 0
            self._last_error = None
            self._wall_started = time.perf_counter()
            return self.snapshot()

    def place_stimulus(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"id", "kind", "x_mm", "y_mm", "radius_mm", "strength"}
        unexpected = set(raw) - allowed
        if unexpected:
            raise ConfigurationError(
                f"Stimulus command contains unsupported fields: {sorted(unexpected)}"
            )
        required = {"id", "kind", "x_mm", "y_mm", "radius_mm"}
        missing = required - set(raw)
        if missing:
            raise ConfigurationError(f"Stimulus command omits {sorted(missing)}")
        x_mm, y_mm = float(raw["x_mm"]), float(raw["y_mm"])
        radius = float(raw["radius_mm"])
        strength = float(raw.get("strength", 1.0))
        if not all(math.isfinite(value) for value in (x_mm, y_mm, radius, strength)):
            raise ConfigurationError("Stimulus values must be finite")
        with self._lock:
            bounds = self._runtime.snapshot()["arena"]["bounds_mm"]
            if not bounds["x"][0] <= x_mm <= bounds["x"][1]:
                raise ConfigurationError("Stimulus x coordinate lies outside the arena")
            if not bounds["y"][0] <= y_mm <= bounds["y"][1]:
                raise ConfigurationError("Stimulus y coordinate lies outside the arena")
            value = self._runtime.place_stimulus(
                stimulus_id=str(raw["id"]),
                kind=str(raw["kind"]),
                x_mm=x_mm,
                y_mm=y_mm,
                radius_mm=radius,
                strength=strength,
            )
            return self._decorate(value)

    def remove_stimulus(self, stimulus_id: str) -> dict[str, Any]:
        with self._lock:
            return self._decorate(self._runtime.remove_stimulus(stimulus_id))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._decorate(self._runtime.snapshot())

    def _decorate(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        elapsed = max(time.perf_counter() - self._wall_started, 1e-9)
        biological_s = snapshot["arena"]["t_us"] / 1_000_000.0
        return {
            **snapshot,
            "service": {
                "running": self._running,
                "step_count": self._step_count,
                "wall_elapsed_s": elapsed,
                "biological_elapsed_s": biological_s,
                "biological_per_wall": biological_s / elapsed,
                "last_error": self._last_error,
                "allowed_client_commands": sorted(ALLOWED_CLIENT_COMMANDS),
                "client_can_write_neural_or_motor_state": False,
            },
        }

    def handle_command(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        command = str(raw.get("command", ""))
        if command not in ALLOWED_CLIENT_COMMANDS:
            raise ConfigurationError(
                f"Unsupported client command {command!r}; "
                f"allowed: {sorted(ALLOWED_CLIENT_COMMANDS)}"
            )
        if command == "start":
            return self.start()
        if command == "pause":
            return self.pause()
        if command == "step":
            return self.step_once()
        if command == "reset":
            return self.reset()
        if command == "place-stimulus":
            payload = raw.get("stimulus")
            if not isinstance(payload, Mapping):
                raise ConfigurationError("place-stimulus needs a stimulus object")
            return self.place_stimulus(payload)
        stimulus_id = str(raw.get("stimulus_id", ""))
        if not stimulus_id:
            raise ConfigurationError("remove-stimulus needs stimulus_id")
        return self.remove_stimulus(stimulus_id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._running = False
            self._closed = True
            self._wake.set()
            self._runtime.close()
        self._thread.join(timeout=5.0)


def create_app(runtime_factory: RuntimeFactory) -> Any:
    """Construct the optional FastAPI application without importing it at package load."""
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - depends on optional installation
        raise ReadinessError(
            "The web extra is not installed. Run `uv sync --extra web` in the project environment."
        ) from exc

    service = LiveDemoService(runtime_factory)

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="MaleCNS Virtual Fly live arena",
        version="0.1.0",
        description="Engineering demonstration; no validation tier is awarded.",
        lifespan=lifespan,
    )
    assets = Path(__file__).resolve().parent / "web_assets"
    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.exception_handler(FlySimError)
    async def flysim_error(_request: Any, exc: FlySimError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": type(exc).__name__, "message": str(exc)},
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(assets / "index.html")

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return service.snapshot()

    @app.post("/api/command")
    async def command(payload: dict[str, Any]) -> dict[str, Any]:
        return service.handle_command(payload)

    async def websocket_endpoint(websocket: Any) -> None:
        await websocket.accept()
        try:
            while True:
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=0.10)
                    payload = json.loads(message)
                    if not isinstance(payload, dict):
                        raise ConfigurationError("WebSocket command must be a JSON object")
                    response = service.handle_command(payload)
                except TimeoutError:
                    response = service.snapshot()
                except (ValueError, FlySimError) as exc:
                    response = {"error": type(exc).__name__, "message": str(exc)}
                await websocket.send_json(response)
        except WebSocketDisconnect:
            return

    # The optional FastAPI classes are imported lazily. Give FastAPI the concrete
    # runtime annotation explicitly instead of leaving a deferred local name that it
    # would misinterpret as a query field.
    websocket_endpoint.__annotations__["websocket"] = WebSocket
    app.websocket("/ws")(websocket_endpoint)

    app.state.flysim_service = service
    return app


def make_runtime_factory(
    *,
    mode: str,
    data_root: Path,
    scenario_path: Path | None,
    seed: int,
    include_shuffled: bool,
) -> RuntimeFactory:
    if mode == "preview":
        return lambda: build_preview_runtime(scenario_path)
    if mode != "full-cns":
        raise ConfigurationError("Web mode must be preview or full-cns")
    return lambda: build_full_cns_runtime(
        data_root=data_root,
        scenario_path=scenario_path,
        seed=seed,
        include_shuffled=include_shuffled,
    )


def run_server(
    *,
    mode: str,
    data_root: Path,
    scenario_path: Path | None,
    seed: int,
    include_shuffled: bool,
    host: str,
    port: int,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional installation
        raise ReadinessError(
            "The web extra is not installed. Run `uv sync --extra web` in the project environment."
        ) from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("Web port must lie in [1, 65535]")
    app = create_app(
        make_runtime_factory(
            mode=mode,
            data_root=data_root,
            scenario_path=scenario_path,
            seed=seed,
            include_shuffled=include_shuffled,
        )
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = [
    "ALLOWED_CLIENT_COMMANDS",
    "LiveDemoService",
    "create_app",
    "make_runtime_factory",
    "run_server",
]
