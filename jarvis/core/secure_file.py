"""Write credential files so only the current user can read them.

API keys (config/api_keys.json), OAuth tokens (config/google_token.json) and
similar files must never be world-readable. ``write_private_text`` creates the
temporary file with mode 0600 *before* any secret is written to it, flushes it
to disk, then atomically replaces the destination, so a crash cannot truncate
the file and there is no window in which another local user can read it.

On Windows the POSIX mode bits are ignored by the OS; files under the user's
profile already inherit a per-user ACL, so no extra step is taken there.
"""
from __future__ import annotations

import os
from pathlib import Path

PRIVATE_MODE = 0o600


def write_private_text(path: os.PathLike[str] | str, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write ``text`` to ``path`` with owner-only permissions."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(temporary, PRIVATE_MODE)  # O_CREAT mode is masked by umask
        os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def restrict_permissions(path: os.PathLike[str] | str) -> bool:
    """Tighten an existing credential file to 0600. Returns True if changed."""
    if os.name == "nt":
        return False
    target = Path(path)
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        return False
    if mode & 0o077:
        try:
            os.chmod(target, PRIVATE_MODE)
            return True
        except OSError:
            return False
    return False
