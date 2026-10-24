import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
for p in [str(ROOT_DIR), str(ROOT_DIR / "JarvisAI"), str(ROOT_DIR / "voice")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from JarvisAI.main import (
    JarvisLive,
    HeadlessJarvisUI,
    TOOL_DECLARATIONS,
    _MIN_LIVE_AUDIO_FRAME_BYTES,
    _MIN_PREBUFFER_BYTES,
    _OUTPUT_BLOCKSIZE,
    _PLAYBACK_SLICE_BYTES,
    _error_text,
    _is_live_operation_aborted,
    _is_transient_live_disconnect,
    _output_write_is_unpaced,
    _pcm_level,
    _take_playback_pcm,
    asyncio,
    get_memory_provider_access_enabled,
    security,
    main,
)

if __name__ == "__main__":
    main()
