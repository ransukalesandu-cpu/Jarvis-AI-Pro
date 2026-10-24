import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
for p in [str(ROOT_DIR), str(ROOT_DIR / "JarvisAI"), str(ROOT_DIR / "voice")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import JarvisAI.main as _jmain

# Re-export everything from JarvisAI.main into this module so `import main`
# or `from main import ...` works seamlessly whether root or JarvisAI/main is referenced.
sys.modules[__name__] = _jmain

if __name__ == "__main__":
    _jmain.main()
