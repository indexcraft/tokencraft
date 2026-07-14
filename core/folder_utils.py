"""
Local filesystem helpers — only meaningful when TokenCraft is running as a
local desktop app (LOCAL_MODE=true). A hosted deployment (e.g. on Wasmer)
has no access to the visiting user's filesystem, so these are never called
in that mode — see app.py's LOCAL_MODE checks.
"""

from __future__ import annotations

import os
import platform
import subprocess


def pick_folder_dialog() -> str | None:
    """Open a native OS folder picker. Only works when the server itself is
    running on the same machine as the person using it (local desktop
    mode) — returns the chosen path, or None if cancelled/unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory()
        root.destroy()
        return folder or None
    except Exception:
        return None


def open_in_explorer(path: str) -> tuple[bool, str]:
    """Open the given folder in the OS file explorer."""
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # noqa: S606
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, ""
    except Exception as e:
        return False, str(e)
