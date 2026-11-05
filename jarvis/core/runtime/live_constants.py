"""Constants shared by jarvis/main.py and the JarvisLive mixins in this package.

They live here so the mixin modules do not have to import ``main``. ``main``
re-exports both names, so ``main.SEND_SAMPLE_RATE`` keeps working.
"""

from concurrent.futures import ThreadPoolExecutor

SEND_SAMPLE_RATE = 16000

# Briefing web searches run here so they never block the real-time audio path.
_BRIEFING_SEARCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="jarvis-briefing-search"
)
