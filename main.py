import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
for p in [str(ROOT_DIR), str(ROOT_DIR / "JarvisAI"), str(ROOT_DIR / "voice")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from JarvisAI.main import *
from JarvisAI.main import (
    _MIN_LIVE_AUDIO_FRAME_BYTES, _PLAYBACK_SLICE_BYTES, _take_playback_pcm, _pcm_level, _MIN_PREBUFFER_BYTES, _OUTPUT_BLOCKSIZE, _error_text,
    _is_live_operation_aborted, _is_transient_live_disconnect, _output_write_is_unpaced
)

if __name__ == "__main__":
    main()
