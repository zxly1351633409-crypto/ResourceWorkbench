"""
HTTP Server for the Electron frontend.

Uses Python stdlib only (no Flask/FastAPI).  All business logic is
delegated to ``ApplicationService``.  Card references use stable
``card_id`` values; legacy array-index endpoints are also supported
for backwards compatibility during transition.
"""

from __future__ import annotations

import json
import mimetypes
import os
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .application_service import get_service

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"
_PREVIEW_DIR = _PROJECT_ROOT / "workbench_data" / "previews"


class HanaAPIHandler(SimpleHTTPRequestHandler):
    """Serves frontend files and JSON REST endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_FRONTEND_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # silent in production; enable for debugging

    # ── service helper ────────────────────────────────────────────
    @property
    def _svc(self):
        return get_service()

    # ── GET routes ─────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ── API ──
        if path == "/api/cards":
            return self._json(self._svc.get_work_cards())

        if path == "/api/settings":
            return self._json(self._svc.get_settings())

        if path == "/api/status":
            return self._json(self._svc.app_status())

        if path == "/api/task-status":
            return self._json(self._svc.task_status())

        if path == "/api/review-queue":
            return self._json(self._svc.get_review_queue())

        if path == "/api/history":
            return self._json(self._svc.get_history())

        # ── Preview image file ──
        if path.startswith("/preview-file/"):
            filename = Path(path).name
            filepath = _PREVIEW_DIR / filename
            if filepath.exists():
                self.send_response(200)
                ct, _ = mimetypes.guess_type(str(filepath))
                self.send_header("Content-Type", ct or "image/png")
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
                return
            self.send_error(404, "Preview not found")
            return

        # ── Preview API (card_id) ──
        if path.startswith("/api/preview/"):
            card_id = path.split("/api/preview/", 1)[1].lstrip("/")
            if card_id:
                return self._json(self._svc.preview(card_id))
            self.send_error(400, "Missing card_id")
            return

        # ── Static files ──
        return super().do_GET()

    # ── POST routes ────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        body = self._read_body()
        data = self._parse_json(body)

        try:
            result = self._route_post(path, data)
            self._json(result)
        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "error": str(e)}, status=500)

    def _route_post(self, path: str, data: dict) -> dict:
        svc = self._svc

        routes: dict[str, callable] = {
            # Scan / Analyse
            "/api/scan": lambda: svc.analyse(data.get("paths", [])),
            "/api/analyze": lambda: svc.analyse(data.get("paths", [])),
            "/api/cancel-analysis": lambda: svc.cancel_analysis(),

            # Library
            "/api/library-tree": lambda: svc.library_tree(data.get("path", "")),
            "/api/library-cards": lambda: svc.library_cards(data.get("path", "")),

            # Translation
            "/api/translate": lambda: self._translate(svc, data),
            "/api/translate-all": lambda: svc.translate_all(),

            # Move
            "/api/move-plan": lambda: svc.plan_card_move(
                data.get("card_id", ""), data.get("target_path", "")
            ),
            "/api/move-execute": lambda: svc.execute_move(
                data.get("card_id", ""), data.get("target_path", "")
            ),
            "/api/move": lambda: self._move_legacy(svc, data),
            "/api/move-selected": lambda: self._move_selected(svc, data),

            # Target recommendation
            "/api/recommend-target": lambda: svc.recommend_target(
                data.get("card_id", "")
            ),

            # Review queue
            "/api/review-queue": lambda: svc.update_review_item(
                data.get("card_id", ""), data.get("status", "")
            ),

            # Settings
            "/api/settings": lambda: svc.save_settings(data),
            "/api/create-folder": lambda: self._create_folder(data),

            # Maintenance
            "/api/open-folder": lambda: svc.open_folder(data.get("path", "")),
            "/api/dedupe": lambda: svc.find_duplicates(),
            "/api/cleanup": lambda: svc.cleanup_empty_dirs(),
            "/api/web-card": lambda: svc.create_web_card(data.get("url", "")),
            "/api/undo": lambda: svc.undo(data.get("kind", ""), data.get("record_id", "")),
            "/api/format": lambda: svc.format_card(data.get("card_id", ""), data.get("apply", False)),
            "/api/metadata": lambda: svc.save_metadata(data.get("card_id", ""), data.get("tags"), data.get("note", "")),
            "/api/mark-review": lambda: svc.mark_review(data.get("card_id", ""), data.get("note", "")),
            "/api/test-deepseek": lambda: svc.test_deepseek(data.get("deepseek_api_key", "")),
            "/api/overview": lambda: svc.get_overview(),

            # Legacy preview by index
            "/api/preview-by-index": lambda: self._preview_by_index(svc, data),
        }

        # ── Legacy preview /api/preview/{index} (POST) ──
        if path.startswith("/api/preview/"):
            card_id = path.split("/api/preview/", 1)[1].lstrip("/")
            if card_id.isdigit():
                return self._preview_by_index(svc, {"index": int(card_id)})
            return svc.preview(card_id)

        # ── Window control (non-svc) ──
        if path == "/api/window-minimize":
            return {"ok": True}
        if path == "/api/window-close":
            return {"ok": True}

        handler = routes.get(path)
        if handler:
            return handler()

        return {"ok": False, "error": f"未知接口: {path}"}

    # ── composite helpers ──────────────────────────────────────────

    def _translate(self, svc, data: dict) -> dict:
        """Support both card_id and legacy index."""
        card_id = data.get("card_id", "")
        if not card_id:
            index = data.get("index", -1)
            if isinstance(index, int) and index >= 0:
                card = svc.store.get_work_by_local_index(index)
                if card:
                    card_id = card.get("card_id", "")
        if not card_id:
            return {"ok": False, "error": "缺少 card_id 或 index"}
        return svc.translate(card_id)

    def _move_legacy(self, svc, data: dict) -> dict:
        card_id = data.get("card_id", "")
        if not card_id:
            index = data.get("index", -1)
            if isinstance(index, int) and index >= 0:
                card = svc.store.get_any_by_local_index(index)
                if card:
                    card_id = card.get("card_id", "")
        if not card_id:
            return {"ok": False, "error": "缺少 card_id 或 index"}
        target = data.get("target_path", "")
        if data.get("dry_run", False):
            return svc.plan_card_move(card_id, target)
        return svc.execute_move(card_id, target)

    def _move_selected(self, svc, data: dict) -> dict:
        card_ids = data.get("card_ids", [])
        if not card_ids:
            indices = data.get("indices", [])
            card_ids = []
            for i in indices:
                card = svc.store.get_work_by_local_index(i)
                if card:
                    card_ids.append(card.get("card_id", ""))
        target = data.get("target_path", "")
        dry_run = data.get("dry_run", False)
        results = []
        for cid in card_ids:
            if dry_run:
                r = svc.plan_card_move(cid, target)
            else:
                r = svc.execute_move(cid, target)
            results.append(r)
        return {"ok": True, "results": results}

    def _preview_by_index(self, svc, data: dict) -> dict:
        index = data.get("index", -1)
        card = svc.store.get_any_by_local_index(index)
        if card is None:
            return {"ok": False, "error": "索引越界"}
        return svc.preview(card.get("card_id", ""))

    # ── HTTP helpers ───────────────────────────────────────────────

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return self.rfile.read(length)
        return b"{}"

    @staticmethod
    def _parse_json(body: bytes) -> dict:
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def create_server(port: int = 9877):
    """Create and return an HTTPServer instance (does not start serving)."""
    return HTTPServer(("127.0.0.1", port), HanaAPIHandler)


def run_server(port: int = 9877, ready_event=None):
    """Start the HTTP server (blocking)."""
    server = create_server(port)
    if ready_event:
        ready_event.set()
    print(f"Hana 工作台服务已启动: http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()
