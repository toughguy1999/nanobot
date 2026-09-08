"""Run from the checkout: uv run python devtools/llm_viewer.py."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / ".nanobot/debug/context.json"
PAGE = Path(__file__).with_suffix(".html")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/context":
            body = CONTEXT_PATH.read_bytes() if CONTEXT_PATH.exists() else b"null"
            content_type = "application/json; charset=utf-8"
        else:
            body = PAGE.read_bytes()
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    print("LLM context viewer: http://127.0.0.1:8766", flush=True)
    HTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
