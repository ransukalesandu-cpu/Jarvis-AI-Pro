"""``cc_file``: file management for computer-control tasks ("organize my project folder").

Default-allow folders (owner decision 5): the policy makes JARVIS secrets, the
JARVIS install folder and Windows system directories HIGH (approval). On top:

* deletes go to the Recycle Bin (``send2trash``), never a permanent delete, and
  are HIGH like every delete;
* nothing is overwritten silently: ``write``/``copy``/``move``/``rename`` onto an
  existing file is refused unless ``overwrite`` is true, which raises the step
  to HIGH;
* file contents and file names read back are untrusted content (fenced, injection-flagged);
* every change is verified on disk (exists / gone / size / text).
"""
from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from jarvis.computer_control.contract import SpecRegistry, ToolSpec
from jarvis.computer_control.runner import ActionContext, ActionOutcome
from jarvis.computer_control.untrusted import wrap

OPS = {"list": "file.list", "read": "file.read", "exists": "file.exists", "stat": "file.stat",
       "search": "file.search", "write": "file.write", "mkdir": "file.mkdir", "copy": "file.copy",
       "move": "file.move", "rename": "file.rename", "delete": "file.delete"}
MAX_READ = 20000
MAX_WRITE = 200_000
MAX_LIST = 300


def _p(value: Any) -> Path:
    text = str(value or "").strip().strip('"')
    if not text:
        raise ValueError("a path is required")
    return Path(os.path.expandvars(text)).expanduser()


def _fail(msg: str) -> ActionOutcome:
    return ActionOutcome(False, msg, verified=False)


def _action_for(params: Mapping[str, Any]) -> str:
    return OPS.get(str(params.get("op") or "list").strip().lower(), "unknown")


def _enrich(params: dict) -> dict:
    if params.get("overwrite") and str(params.get("op")) in ("write", "copy", "move", "rename"):
        params["requested_level"] = "high"            # replacing data needs the owner
    if str(params.get("op")) == "rename" and params.get("path") and params.get("new_name"):
        params["dst"] = str(_p(params["path"]).with_name(str(params["new_name"])))
    return params


def _handler(ctx: ActionContext) -> ActionOutcome:
    p = ctx.params
    op = str(p.get("op") or "list").lower()
    if p.get("overwrite") and op in ("write", "copy", "move", "rename"):
        # replacing data needs the owner; refuse unless this call really was approved HIGH
        # (the policy-time lookup that raises it could have failed)
        from jarvis.computer_control.policy import Level
        if getattr(ctx, "level", None) is not Level.HIGH:
            return _fail("Replacing an existing file needs your approval; nothing was changed.")
    try:
        if op == "list":
            folder = _p(p.get("path") or ".")
            if not folder.is_dir():
                return _fail(f"{folder} is not a folder.")
            items = sorted(folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.casefold()))[:MAX_LIST]
            rows = [{"name": i.name, "dir": i.is_dir(), "bytes": i.stat().st_size if i.is_file() else None}
                    for i in items]
            names = wrap(", ".join(r["name"] + ("/" if r["dir"] else "") for r in rows[:40]), "file")
            return ActionOutcome(True, f"{len(rows)} item(s) in {folder}:\n" + names.for_model(4000),
                                 data={"items": rows, "folder": str(folder)}, verified=True)
        if op in ("exists", "stat"):
            target = _p(p.get("path"))
            if not target.exists():
                return ActionOutcome(op == "exists", f"{target} does not exist.", data={"exists": False},
                                     verified=True)
            st = target.stat()
            return ActionOutcome(True, f"{target} exists ({'folder' if target.is_dir() else f'{st.st_size} bytes'}).",
                                 data={"exists": True, "dir": target.is_dir(), "bytes": st.st_size,
                                       "modified": st.st_mtime}, verified=True)
        if op == "read":
            target = _p(p.get("path"))
            if not target.is_file():
                return _fail(f"{target} is not a file.")
            text = target.read_text(encoding="utf-8", errors="replace")[:MAX_READ]
            content = wrap(text, "file")
            return ActionOutcome(True, content.for_model(MAX_READ), data={"chars": len(text),
                                 "injection_flags": list(content.flags)}, verified=True)
        if op == "search":
            folder = _p(p.get("path") or ".")
            pattern = str(p.get("pattern") or "*")
            hits = []
            for root, dirs, files in os.walk(folder):
                ctx.check()
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
                for name in files:
                    if fnmatch.fnmatch(name.casefold(), pattern.casefold()):
                        hits.append(str(Path(root) / name))
                        if len(hits) >= MAX_LIST:
                            break
                if len(hits) >= MAX_LIST:
                    break
            return ActionOutcome(True, f"{len(hits)} file(s) match {pattern}.", data={"files": hits}, verified=True)
        if op == "mkdir":
            target = _p(p.get("path"))
            target.mkdir(parents=True, exist_ok=True)
            return ActionOutcome(True, f"Folder {target} is ready.", verified=target.is_dir(),
                                 evidence="folder exists")
        if op == "write":
            target = _p(p.get("path"))
            text = str(p.get("text") or "")
            if len(text) > MAX_WRITE:
                return _fail("That is too much text for one write.")
            if target.exists() and not p.get("overwrite"):
                return _fail(f"{target.name} already exists; say overwrite to replace it.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            ok = target.read_text(encoding="utf-8") == text
            return ActionOutcome(True, f"Wrote {len(text)} characters to {target}.", data={"path": str(target)},
                                 verified=ok, evidence="file reads back the same text" if ok else "content differs")
        if op in ("copy", "move", "rename"):
            src = _p(p.get("path") or p.get("src"))
            dst = _p(p.get("dst") or (src.with_name(str(p.get("new_name"))) if p.get("new_name") else ""))
            if not src.exists():
                return _fail(f"{src} does not exist.")
            if dst.is_dir() and op != "rename":
                dst = dst / src.name
            if dst.exists() and not p.get("overwrite"):
                return _fail(f"{dst.name} already exists at the destination; nothing was replaced.")
            dst.parent.mkdir(parents=True, exist_ok=True)
            ctx.check()
            if op == "copy":
                (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
                ok = dst.exists() and src.exists()
            else:
                shutil.move(str(src), str(dst))
                ok = dst.exists() and not src.exists()
            verb = {"copy": "Copied", "move": "Moved", "rename": "Renamed"}[op]
            return ActionOutcome(True, f"{verb} {src.name} to {dst}.", data={"from": str(src), "to": str(dst)},
                                 verified=ok, evidence="destination present" + ("" if op == "copy" else
                                                                               ", source gone"))
        if op == "delete":
            target = _p(p.get("path"))
            if not target.exists():
                return _fail(f"{target} does not exist.")
            try:
                from send2trash import send2trash
            except Exception:
                return _fail("Deleting needs the 'send2trash' package (Recycle Bin); nothing was deleted.")
            send2trash(str(target))
            gone = not target.exists()
            return ActionOutcome(True, f"Moved {target.name} to the Recycle Bin.", verified=gone,
                                 evidence="no longer at its path" if gone else "still present")
    except (OSError, ValueError) as exc:
        return _fail(f"{op} failed: {exc}")
    return _fail(f"Unknown op '{op}'.")


def register(reg: SpecRegistry) -> None:
    S = "STRING"
    reg.register(ToolSpec(
        id="cc_file", action="file.list",
        description=("Files and folders: list, read (text, as data), exists, stat, search (glob), write (no "
                     "silent overwrite), mkdir, copy, move, rename, delete (to the Recycle Bin, needs approval)."),
        input_schema={"type": "OBJECT", "properties": {
            "op": {"type": S, "enum": list(OPS)}, "path": {"type": S}, "dst": {"type": S},
            "new_name": {"type": S}, "text": {"type": S}, "pattern": {"type": S},
            "overwrite": {"type": "BOOLEAN", "description": "Replace an existing file (needs approval)."}},
            "required": ["op"]},
        handler=_handler, timeout=120.0, action_for=_action_for, enrich=_enrich))
