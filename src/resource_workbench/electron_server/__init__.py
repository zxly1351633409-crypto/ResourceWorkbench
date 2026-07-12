"""electron_server — HTTP API layer for Electron frontend.

Replaces backend_bridge.py with a formally designed service layer
that integrates directly with the original ResourceWorkbench modules.
"""

__all__ = [
    "ApplicationService",
    "CardStore",
    "TaskManager",
    "run_server",
]
