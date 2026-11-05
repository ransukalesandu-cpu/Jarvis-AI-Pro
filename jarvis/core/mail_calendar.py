"""Provider interface for email and calendar, so neither tool is tied to one service.

The ``email`` and ``calendar`` tools (actions/email_tool.py,
actions/calendar_tool.py) talk only to these interfaces. A provider is any
object implementing :class:`MailProvider` or :class:`CalendarProvider` that
registers itself, typically from a plugin file at import time::

    from core.mail_calendar import register_mail_provider
    register_mail_provider(MyImapProvider())

The reference implementation is Gmail + Google Calendar
(plugins/_google_providers.py). A provider whose ``is_configured()`` is False
is ignored, and the tools stay hidden from Gemini until one is configured.

Everything a provider returns from a mailbox or calendar is untrusted content
(anyone can send an email); the tools wrap it with core.injection_guard before
it reaches the model.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Optional


class MailProvider(ABC):
    name = "mail"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        """[{id, from, subject, date, snippet}]"""

    @abstractmethod
    def read_message(self, message_id: str) -> dict:
        """{id, from, to, subject, date, body}"""

    @abstractmethod
    def create_draft(self, to: str, subject: str, body: str) -> str:
        """Returns the draft id."""

    @abstractmethod
    def send_message(self, to: str, subject: str, body: str) -> str:
        """Returns the sent message id."""


class CalendarProvider(ABC):
    name = "calendar"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def list_events(self, days: int = 1, max_results: int = 10) -> list[dict]:
        """[{id, title, start, end, location}] from now until now + days."""

    @abstractmethod
    def create_event(self, title: str, start_iso: str, end_iso: str,
                     description: str = "", location: str = "") -> dict:
        """Returns {id, title, start, end, link}."""


_lock = threading.Lock()
_mail: list[MailProvider] = []
_calendar: list[CalendarProvider] = []
_defaults_loaded = False


def register_mail_provider(provider: MailProvider) -> None:
    with _lock:
        _mail[:] = [p for p in _mail if p.name != provider.name] + [provider]


def register_calendar_provider(provider: CalendarProvider) -> None:
    with _lock:
        _calendar[:] = [p for p in _calendar if p.name != provider.name] + [provider]


def _load_defaults() -> None:
    global _defaults_loaded
    if _defaults_loaded:
        return
    _defaults_loaded = True
    try:
        import jarvis.plugins._google_providers  # noqa: F401 - registers on import
    except Exception as exc:
        print(f"[MailCalendar] Google providers unavailable: {type(exc).__name__}: {exc}")


def _first_configured(providers: list) -> Optional[object]:
    for provider in list(providers):
        try:
            if provider.is_configured():
                return provider
        except Exception as exc:
            print(f"[MailCalendar] {getattr(provider, 'name', provider)} check failed: {exc}")
    return None


def mail_provider() -> Optional[MailProvider]:
    _load_defaults()
    return _first_configured(_mail)


def calendar_provider() -> Optional[CalendarProvider]:
    _load_defaults()
    return _first_configured(_calendar)


def reset_for_tests() -> None:
    global _defaults_loaded
    with _lock:
        _mail.clear()
        _calendar.clear()
    _defaults_loaded = True     # tests register their own providers
