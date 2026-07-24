from __future__ import annotations

import atexit
import json
import mimetypes
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bim_ai.storage import add_audit_event, get_project, set_viewer_selection


VIEWER_DIR = Path(__file__).resolve().parent.parent / "viewer"
VIEWER_DIST_DIR = VIEWER_DIR / "dist"
FRAGMENT_CONVERTER = VIEWER_DIR / "scripts" / "convert-ifc.mjs"
_RUNNING_SERVERS: list[tuple["_ViewerServer", threading.Thread]] = []
_RUNNING_SERVERS_LOCK = threading.Lock()


class _ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, db_path: Path):
        super().__init__(server_address, handler_class)
        self.db_path = db_path
        self.fragment_locks: dict[int, threading.Lock] = {}
        self.fragment_locks_guard = threading.Lock()

    def fragment_lock(self, project_id: int) -> threading.Lock:
        with self.fragment_locks_guard:
            return self.fragment_locks.setdefault(project_id, threading.Lock())


class _ViewerHandler(BaseHTTPRequestHandler):
    server: _ViewerServer

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path in {"/", "/index.html"}:
            self._send_file(
                VIEWER_DIST_DIR / "index.html",
                "text/html; charset=utf-8",
                cache_control="no-store",
            )
            return
        if request.path == "/fragment":
            self._send_fragment(parse_qs(request.query))
            return
        if request.path == "/model":
            self._send_model(parse_qs(request.query))
            return
        self._send_static(request.path)

    def _send_static(self, request_path: str) -> None:
        relative_path = request_path.lstrip("/")
        if not relative_path:
            self.send_error(404)
            return
        path = (VIEWER_DIST_DIR / relative_path).resolve()
        if not path.is_relative_to(VIEWER_DIST_DIR.resolve()) or not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".mjs":
            content_type = "text/javascript"
        self._send_file(
            path,
            content_type,
            cache_control="public, max-age=31536000, immutable",
        )

    def do_POST(self) -> None:
        request = urlparse(self.path)
        if request.path != "/selection":
            self.send_error(404)
            return
        self._save_selection()

    def _save_selection(self) -> None:
        project_id: int | None = None
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 4096:
                raise ValueError("Invalid request body")
            payload = json.loads(self.rfile.read(content_length))
            project_id = int(payload["project_id"])
            project = get_project(self.server.db_path, project_id)
            model = self._load_project_model(project)
            has_step_id = payload.get("step_id") is not None
            has_global_id = payload.get("global_id") is not None
            if has_step_id == has_global_id:
                raise ValueError("Provide exactly one IFC identifier")
            if has_step_id:
                entity = model.by_id(int(payload["step_id"]))
            else:
                global_id = str(payload["global_id"])
                if not global_id or len(global_id) > 64:
                    raise ValueError("Invalid IFC GlobalId")
                entity = model.by_guid(global_id)
            if entity is None:
                raise ValueError("IFC entity was not found")
            step_id = entity.id()
            info = entity.get_info(recursive=False)
            set_viewer_selection(
                self.server.db_path,
                project_id,
                step_id,
                entity.is_a(),
                info.get("GlobalId"),
                info.get("Name"),
            )
            add_audit_event(
                self.server.db_path,
                project_id,
                None,
                "viewer_selection",
                "completed",
                {
                    "step_id": step_id,
                    "ifc_type": entity.is_a(),
                    "global_id": info.get("GlobalId"),
                    "name": info.get("Name"),
                },
            )
        except Exception as exc:
            if project_id is not None:
                add_audit_event(
                    self.server.db_path,
                    project_id,
                    None,
                    "viewer_selection",
                    "error",
                    {"error": str(exc)[:500]},
                )
            self._send_json(400, {"error": "Invalid IFC selection"})
            return

        self._send_json(
            200,
            {
                "step_id": step_id,
                "ifc_type": entity.is_a(),
                "global_id": info.get("GlobalId"),
                "name": info.get("Name"),
            },
        )

    def _load_project_model(self, project: dict) -> object:
        try:
            import ifcopenshell
        except ImportError as exc:
            raise RuntimeError("IfcOpenShell is unavailable") from exc
        model_path = self._project_model_path(project)
        return ifcopenshell.open(str(model_path))

    def _project_model_path(self, project: dict) -> Path:
        model_path = Path(project["ifc_path"]).resolve()
        project_root = (Path(self.server.db_path).parent / "projects").resolve()
        if not model_path.is_relative_to(project_root) or model_path.suffix.lower() != ".ifc":
            raise ValueError("Invalid project model path")
        return model_path

    def _project_request(
        self,
        query: dict[str, list[str]],
    ) -> tuple[int, dict, Path] | None:
        try:
            project_id = int(query["project_id"][0])
            project = get_project(self.server.db_path, project_id)
            model_path = self._project_model_path(project)
        except (KeyError, ValueError, TypeError):
            self.send_error(400, "Invalid project_id")
            return None

        if not model_path.is_file():
            self.send_error(404, "IFC model not found")
            return None
        return project_id, project, model_path

    def _send_model(self, query: dict[str, list[str]]) -> None:
        request = self._project_request(query)
        if request is None:
            return
        _, _, model_path = request
        self._send_file(model_path, "application/octet-stream")

    def _send_fragment(self, query: dict[str, list[str]]) -> None:
        request = self._project_request(query)
        if request is None:
            return
        project_id, _, model_path = request

        try:
            with self.server.fragment_lock(project_id):
                fragment_path, converted = self._ensure_fragment(model_path)
            if converted:
                add_audit_event(
                    self.server.db_path,
                    project_id,
                    None,
                    "fragment_conversion",
                    "completed",
                    {
                        "ifc_bytes": model_path.stat().st_size,
                        "fragment_bytes": fragment_path.stat().st_size,
                    },
                )
        except Exception as exc:
            add_audit_event(
                self.server.db_path,
                project_id,
                None,
                "fragment_conversion",
                "error",
                {"error": str(exc)[:500]},
            )
            self.send_error(503, f"Fragments conversion failed: {exc}")
            return

        self._send_file(
            fragment_path,
            "application/octet-stream",
            cache_control="no-store",
        )

    def _ensure_fragment(self, model_path: Path) -> tuple[Path, bool]:
        fragment_path = model_path.with_suffix(".frag")
        source_stat = model_path.stat()
        if (
            fragment_path.is_file()
            and fragment_path.stat().st_mtime_ns >= source_stat.st_mtime_ns
        ):
            return fragment_path, False

        node_path = self._find_node()
        if not FRAGMENT_CONVERTER.is_file():
            raise RuntimeError("viewer conversion script is missing")
        if not (VIEWER_DIR / "node_modules" / "@thatopen" / "fragments").is_dir():
            raise RuntimeError("viewer dependencies are missing; run pnpm install in viewer")

        temporary_path = fragment_path.with_suffix(".frag.tmp")
        try:
            result = subprocess.run(
                [
                    str(node_path),
                    "--max-old-space-size=8192",
                    str(FRAGMENT_CONVERTER),
                    str(model_path),
                    str(temporary_path),
                ],
                cwd=VIEWER_DIR,
                capture_output=True,
                text=True,
                timeout=15 * 60,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(detail[-1000:] or "converter exited with an error")
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise RuntimeError("converter produced an empty fragment")
            os.replace(temporary_path, fragment_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        return fragment_path, True

    @staticmethod
    def _find_node() -> Path:
        configured = os.getenv("BIM_AI_NODE_PATH")
        if configured:
            path = Path(configured).expanduser().resolve()
            if path.is_file():
                return path
            raise RuntimeError("BIM_AI_NODE_PATH does not point to a Node.js executable")

        discovered = shutil.which("node")
        if discovered:
            return Path(discovered).resolve()

        bundled = (
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        )
        if bundled.is_file():
            return bundled
        raise RuntimeError("Node.js was not found; install Node.js or set BIM_AI_NODE_PATH")

    def _send_file(
        self,
        path: Path,
        content_type: str,
        cache_control: str = "no-store",
    ) -> None:
        try:
            size = path.stat().st_size
            with path.open("rb") as source:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", cache_control)
                self.end_headers()
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        except (FileNotFoundError, BrokenPipeError):
            return

    def _send_json(self, status: int, payload: dict) -> None:
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args) -> None:
        return


def start_viewer_server(db_path: Path) -> str:
    server = _ViewerServer(("127.0.0.1", 0), _ViewerHandler, db_path)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"ifc-viewer-{server.server_port}",
        daemon=True,
    )
    thread.start()
    with _RUNNING_SERVERS_LOCK:
        _RUNNING_SERVERS.append((server, thread))
    return f"http://127.0.0.1:{server.server_port}"


def stop_viewer_servers() -> None:
    with _RUNNING_SERVERS_LOCK:
        running_servers = list(_RUNNING_SERVERS)
        _RUNNING_SERVERS.clear()

    for server, thread in running_servers:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        thread.join(timeout=2)


atexit.register(stop_viewer_servers)


def _run_standalone() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the BIM AI viewer server")
    parser.add_argument("--db", type=Path, default=Path("data/app.db"))
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    server = _ViewerServer(
        ("127.0.0.1", args.port),
        _ViewerHandler,
        args.db.resolve(),
    )
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    _run_standalone()
