from __future__ import annotations

import os
from typing import Any


DEFAULT_GRACEFUL_SHUTDOWN_SECONDS = 5


def _shutdown_timeout_seconds() -> int:
    raw_value = os.getenv(
        "BIM_AI_SHUTDOWN_TIMEOUT",
        str(DEFAULT_GRACEFUL_SHUTDOWN_SECONDS),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_GRACEFUL_SHUTDOWN_SECONDS


def _prepare_uvicorn_stop(server: Any, timeout: int) -> None:
    config = getattr(server, "config", None)
    if config is not None:
        config.timeout_graceful_shutdown = timeout

    # Streamlit handles SIGINT itself, so Uvicorn never receives the second
    # Ctrl+C that would normally set force_exit. Restore that behavior here.
    if getattr(server, "should_exit", False):
        server.force_exit = True


def install_streamlit_shutdown_guard() -> bool:
    """Bound Streamlit/Uvicorn shutdown time and restore force-quit behavior."""
    try:
        from streamlit.web.server.starlette.starlette_server import UvicornServer
    except (ImportError, AttributeError):
        # Older Streamlit releases use Tornado and do not need this guard.
        return False

    current_stop = UvicornServer.stop
    if getattr(current_stop, "_bim_ai_shutdown_guard", False):
        return True

    timeout = _shutdown_timeout_seconds()

    def guarded_stop(self: Any) -> None:
        server = getattr(self, "_server", None)
        if server is not None:
            _prepare_uvicorn_stop(server, timeout)
        current_stop(self)

    guarded_stop._bim_ai_shutdown_guard = True  # type: ignore[attr-defined]
    UvicornServer.stop = guarded_stop
    return True
