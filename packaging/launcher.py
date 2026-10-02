"""Entry point for the Windows .exe (PyInstaller).

Double-click: starts the web interface and opens it in the browser.
From a terminal the normal commands work, e.g. ``EVEReactionDing.exe calc --top 10``.
"""

from reactionding.cli import run

run()
