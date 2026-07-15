from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bim_ai.storage import get_project


VIEWER_DIR = Path(__file__).resolve().parent.parent / "viewer"


class _ViewerServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, db_path: Path):
        super().__init__(server_address, handler_class)
        self.db_path = db_path


class _ViewerHandler(BaseHTTPRequestHandler):
    server: _ViewerServer

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path in {"/", "/index.html"}:
            self._send_file(VIEWER_DIR / "index.html", "text/html; charset=utf-8")
            return
        if request.path == "/model":
            self._send_model(parse_qs(request.query))
            return
        self.send_error(404)

    def _send_model(self, query: dict[str, list[str]]) -> None:
        try:
            project_id = int(query["project_id"][0])
            project = get_project(self.server.db_path, project_id)
            model_path = Path(project["ifc_path"]).resolve()
            project_root = Path(self.server.db_path).parent / "projects"
            if not model_path.is_relative_to(project_root.resolve()) or model_path.suffix.lower() != ".ifc":
                raise ValueError("Invalid project model path")
        except (KeyError, ValueError, TypeError):
            self.send_error(400, "Invalid project_id")
            return

        if not model_path.is_file():
            self.send_error(404, "IFC model not found")
            return
        self._send_file(model_path, "application/octet-stream")

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            size = path.stat().st_size
            with path.open("rb") as source:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        except (FileNotFoundError, BrokenPipeError):
            return

    def log_message(self, format: str, *args) -> None:
        return


def start_viewer_server(db_path: Path) -> str:
    server = _ViewerServer(("127.0.0.1", 0), _ViewerHandler, db_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_port}"
