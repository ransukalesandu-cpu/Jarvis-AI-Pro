"""Safe Qt WebEngine Chromium flag construction."""

from __future__ import annotations


def qtwebengine_chromium_flags(platform_name: str, existing_flags: str = "") -> str:
    """Preserve explicit flags and enable Windows GPU hints without disabling sandboxing."""
    flags = str(existing_flags or "").split()
    if str(platform_name or "").casefold() == "windows":
        for flag in ("--enable-gpu-rasterization", "--enable-zero-copy"):
            if flag not in flags:
                flags.append(flag)
    return " ".join(flags)
