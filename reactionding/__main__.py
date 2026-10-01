import os
import sys

from .cli import main

try:
    code = main()
    sys.stdout.flush()
except BrokenPipeError:
    # Output was piped into a program that stopped reading (e.g. `| head`).
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    code = 0
sys.exit(code)
