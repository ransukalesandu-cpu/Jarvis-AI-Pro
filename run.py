import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for p in [ROOT, ROOT / "JarvisAI", ROOT / "voice"]:
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from JarvisAI.main import main

if __name__ == "__main__":
    main()
