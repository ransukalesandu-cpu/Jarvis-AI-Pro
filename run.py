"""
Root runner for JARVIS AI.
Usage:
    python run.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
for path in [str(ROOT), str(ROOT / "JarvisAI"), str(ROOT / "voice")]:
    if path not in sys.path:
        sys.path.insert(0, path)

from JarvisAI.main import *

if __name__ == "__main__":
    main()
