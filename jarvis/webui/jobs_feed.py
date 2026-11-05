"""Read-only mirror of the background-job list for the web page, plus a guarded cancel.

Source of truth is :class:`jarvis.core.jobs.JobManager`; this only publishes a result-free snapshot (id, name, status,
times) to the state bus whenever a job starts or ends. Job results and descriptions are never forwarded.
"""
from __future__ import annotations

from jarvis.core import ui_state


def _row(j: dict) -> tuple:
    return (str(j["id"]), str(j["name"]), str(j["status"]), float(j["started"]), float(j["finished"]) if j.get("finished") else None)


class JobsFeed:
    def __init__(self, manager, bus=None):
        self._manager = manager
        self._bus = bus or ui_state.bus()
        self._unsub = manager.add_listener(self.publish)
        self.publish()

    def publish(self) -> None:
        self._bus.set(ui_state.JOBS, tuple(_row(j) for j in self._manager.snapshot()))

    def close(self) -> None:
        self._unsub()
