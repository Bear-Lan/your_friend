"""Entry point for the Windows service bundled alongside the Flutter app."""

import multiprocessing
import os
import sys
from pathlib import Path

from yf.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.stdout is None or sys.stderr is None:
        logs = Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / "your_friend" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stream = (logs / "service.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    main()
