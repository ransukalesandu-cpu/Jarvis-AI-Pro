"""Import qfluentwidgets once, without its promotional banner on stdout."""
from __future__ import annotations

import contextlib
import io

with contextlib.redirect_stdout(io.StringIO()):
    import qfluentwidgets as fluent  # noqa: E402

__all__ = ["fluent"]
