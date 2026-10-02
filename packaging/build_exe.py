"""Builds dist/EVEReactionDing.exe with PyInstaller. Run on Windows:

    pip install pyinstaller openpyxl
    python packaging/build_exe.py
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
PyInstaller.__main__.run([
    str(ROOT / "packaging" / "launcher.py"),
    "--name", "EVEReactionDing",
    "--onefile",
    "--console",  # the window shows the server log; closing it stops the program
    "--clean",
    "--noconfirm",
    "--paths", str(ROOT),
    "--collect-submodules", "reactionding",
    "--hidden-import", "openpyxl",
    "--add-data", f"{ROOT / 'reactionding' / 'web'}{os.pathsep}reactionding/web",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    *sys.argv[1:],
])
