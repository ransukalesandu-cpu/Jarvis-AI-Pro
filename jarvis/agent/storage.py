"""Choose where autonomous tasks are persisted: on this PC (default) or in Supabase.

The owner picks with ``autonomous_task_storage`` in ``config/api_keys.json`` (or
``JARVIS_AGENT_STORAGE``); see :mod:`agent.settings`.

* ``local`` — :class:`agent.store.TaskStore`: an atomic JSON snapshot plus an
  fsynced journal per task, every string redacted before it is written. Works
  offline and needs no account, so autonomous tasks always have somewhere to live.
* ``cloud`` — :class:`agent.cloud_store.CloudTaskStore`: Supabase only, nothing on
  disk. It fails closed: when Supabase is missing or unreachable the task does not
  start (or pauses) and the reason is reported. It never falls back to local storage
  behind the owner's back.

Status text never contains a local filesystem path; those can carry the Windows
user name and status is read back to the cloud model.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from jarvis.agent.settings import TASK_STORAGE_CLOUD, TASK_STORAGE_LOCAL, AgentSettings

STORAGE_INJECTED = "injected"

_LABELS = {
    TASK_STORAGE_LOCAL: "local, on this PC",
    TASK_STORAGE_CLOUD: "Supabase cloud (no local copy)",
    STORAGE_INJECTED: "custom store",
}


@dataclass(frozen=True)
class StorageChoice:
    kind: str           # "local", "cloud" or "injected"
    label: str          # short owner-facing description, never a path


def cloud_configuration_problem() -> str:
    """Why cloud task storage cannot work right now, or "" when it is configured.

    Cheap and offline: it only checks the public settings the request needs. The
    sign-in and the request itself can still fail later; those errors are reported
    by the store and never answered with a local fallback.
    """
    missing = [name for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY")
               if not os.getenv(name, "").strip()]
    if missing:
        return " and ".join(missing) + (" is" if len(missing) == 1 else " are") + " not set"
    return ""


def select_task_store(settings: AgentSettings) -> tuple[Any, StorageChoice]:
    """Return the store for ``settings.task_storage`` and a description of it."""
    if settings.task_storage == TASK_STORAGE_CLOUD:
        from jarvis.agent.cloud_store import CloudTaskStore
        return CloudTaskStore(), StorageChoice(TASK_STORAGE_CLOUD, _LABELS[TASK_STORAGE_CLOUD])
    from jarvis.agent.store import TaskStore
    return TaskStore(), StorageChoice(TASK_STORAGE_LOCAL, _LABELS[TASK_STORAGE_LOCAL])


def injected_choice() -> StorageChoice:
    return StorageChoice(STORAGE_INJECTED, _LABELS[STORAGE_INJECTED])


def cloud_unavailable_message(problem: str) -> str:
    return (f"Autonomous task storage is set to Supabase cloud, but {problem}. "
            "Finish the Supabase setup, or switch task storage to local "
            "(autonomous_task_storage = \"local\").")
