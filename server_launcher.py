"""
ResourceWorkbench Electron Server — 顶层启动入口。

由 Electron main.js 通过 ``python server_launcher.py`` 启动。
默认端口 9877。
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the src/ package root is on sys.path
_project = Path(__file__).resolve().parent
_src = _project / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from resource_workbench.electron_server.server import run_server

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9877
    run_server(port=port)
