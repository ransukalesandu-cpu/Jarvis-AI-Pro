import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
for p in [str(ROOT_DIR), str(ROOT_DIR / "JarvisAI"), str(ROOT_DIR / "voice")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import JarvisAI.main as _jmain
for _k, _v in _jmain.__dict__.items():
    if not _k.startswith("__"):
        globals()[_k] = _v

if __name__ == "__main__":
    main()
