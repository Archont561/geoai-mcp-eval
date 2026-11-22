#!/usr/bin/env python3
"""
Simple static server for the patched myst build.
Handles /geoai-mcp-eval/ base URL prefix.
Serves from docs/_build/html/ and docs/assets/.
"""

from __future__ import annotations

import http.server
import os
from pathlib import Path

from tasknest import ToolContext, tool

DOCS_ROOT = Path("docs")
BUILD_DIR = DOCS_ROOT / "_build" / "html"
ASSETS_DIR = DOCS_ROOT / "assets"
BASE_URL = "/geoai-mcp-eval/"
ASSETS_PATH = "/assets/"


class PatchedHandler(http.server.SimpleHTTPRequestHandler):
    """Request handler that strips the base URL prefix and maps paths."""

    def translate_path(self, path: str) -> str:
        """Strip the base URL prefix and map to build or assets directory."""
        # Strip the base URL prefix
        if path.startswith(BASE_URL):
            path = path[len(BASE_URL) - 1:]  # keep leading slash
        elif path == "/":
            path = "/index.html"

        # Map to build dir
        if path.startswith(ASSETS_PATH):
            # Serve from docs/assets/ (e.g. /assets/marimo-islands/main.js
            # -> docs/assets/marimo-islands/main.js)
            rel = path[len(ASSETS_PATH):]
            return str(ASSETS_DIR / rel)
        else:
            # Serve from docs/_build/html/
            rel = path[1:] if path.startswith("/") else path
            # Try directory index
            candidate = BUILD_DIR / rel
            if candidate.is_dir():
                return str(candidate / "index.html")
            return str(BUILD_DIR / rel)

    def end_headers(self) -> None:
        """Add cache control headers for assets."""
        # Cache control for assets
        if self.path.startswith(ASSETS_PATH):
            self.send_header(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        super().end_headers()


@tool(description="Serve the patched MyST build statically on port 8888.")
def serve_patched(ctx: ToolContext) -> None:
    """Serve the patched MyST build statically on port 8888 (blocking)."""
    os.chdir(str(ctx.repo_root))
    server = http.server.HTTPServer(("0.0.0.0", 8888), PatchedHandler)
    print(f"Serving patched build on http://0.0.0.0:8888{BASE_URL}")
    print(f"Build dir: {BUILD_DIR}")
    print(f"Assets dir: {ASSETS_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    print("Run via: pixi run tools serve_patched")
