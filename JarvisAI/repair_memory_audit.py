"""Explicit, backup-first recovery for a broken local JARVIS memory audit chain.

Run only while JARVIS is closed. The prior audit chain cannot be retroactively
validated after repair; the script preserves a full local backup and appends a
signed audit event recording that recovery was performed.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from memory.memory_manager import (  # noqa: E402
    MEMORY_PATH,
    _append_audit,
    _empty_memory,
    _migrate_memory_data,
    _resign_audit,
)
from memory.memory_store import database_path, load_snapshot, save_snapshot  # noqa: E402
from memory.memory_audit import verify_chain  # noqa: E402


def _backup_sources(backup_dir: Path, db_path: Path, key_path: Path, anchor_path: Path) -> None:
    """Back up all local files needed to restore the pre-repair state."""
    backup_dir.mkdir(parents=True, exist_ok=False)

    if db_path.is_file():
        target = backup_dir / db_path.name
        # SQLite's backup API also captures committed WAL data consistently.
        source = sqlite3.connect(str(db_path))
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    for source_path, name in (
        (MEMORY_PATH, MEMORY_PATH.name),
        (key_path, key_path.name),
        (anchor_path, anchor_path.name),
    ):
        if source_path.is_file():
            shutil.copy2(source_path, backup_dir / name)


def main() -> int:
    print("JARVIS MEMORY AUDIT RECOVERY")
    print("=" * 34)
    print("Close JARVIS before continuing.")
    print("This preserves the local memories and audit rows, but the old chain")
    print("cannot be retroactively verified after it is re-signed.")
    try:
        input("Press Enter to create a backup and repair the local audit chain, or Ctrl+C to cancel... ")
    except (KeyboardInterrupt, EOFError):
        print("Cancelled; no changes made.")
        return 1

    db_path = database_path(MEMORY_PATH)
    key_path = BASE_DIR / "config" / "memory_audit.key"
    anchor_path = BASE_DIR / "config" / "memory_audit.anchor"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = BASE_DIR / "memory" / "audit-recovery-backups" / stamp

    try:
        # Preserve the exact pre-repair state before inspecting or changing it.
        _backup_sources(backup_dir, db_path, key_path, anchor_path)

        # Fail closed if the signing key has disappeared while signed records or
        # a checkpoint remain; recreating it would falsely imply prior integrity.
        if not key_path.exists() and (
            anchor_path.exists()
            or (
                db_path.exists()
                and any(
                    isinstance(row, dict) and row.get("hmac")
                    for row in (load_snapshot(MEMORY_PATH) or {}).get("memory_audit", [])
                )
            )
        ):
            raise RuntimeError(
                "The audit signing key is missing while signed history exists. "
                "The pre-repair backup has been preserved; manual recovery is required."
            )
        if key_path.exists() and len(key_path.read_bytes()) < 16:
            raise RuntimeError(
                "The audit signing key is empty or truncated. "
                "The pre-repair backup has been preserved; manual recovery is required."
            )

        if db_path.exists():
            memory = load_snapshot(MEMORY_PATH)
            if not isinstance(memory, dict):
                raise RuntimeError("The SQLite memory database could not be read.")
        elif MEMORY_PATH.exists():
            memory = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if not isinstance(memory, dict):
                raise RuntimeError("The legacy memory file is not a JSON object.")
        else:
            memory = _empty_memory()

        memory = _migrate_memory_data(memory)
        # Preserve existing audit rows in order, then deliberately re-sign them.
        # The backup above is the record of the chain as it was before recovery.
        _resign_audit(memory)
        _append_audit(
            memory,
            "system:memory-audit",
            "audit_chain_recovered",
            "local_admin",
            "User invoked the local backup-first audit recovery utility; previous chain was not verified.",
        )
        save_snapshot(MEMORY_PATH, memory, allow_audit_repair=True)

        result = verify_chain()
        if not result.get("valid"):
            raise RuntimeError(
                f"Verification after recovery failed: {result.get('reason', 'unknown reason')}"
            )
        print()
        print("Recovery complete. New audit chain verified.")
        print(f"Backup folder: {backup_dir}")
        print("Restart JARVIS and try saving memory again.")
        return 0
    except Exception as exc:
        print()
        print(f"Recovery failed safely: {type(exc).__name__}: {exc}")
        print("Do not delete the backup folder or memory/config files.")
        print(f"Backup folder (if created): {backup_dir}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
