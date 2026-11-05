"""Reference mail/calendar providers: Gmail and Google Calendar.

Configured when both the OAuth client file and an authorized token exist
(config/google_credentials.json + config/google_token.json, or the paths in
JARVIS_GOOGLE_CREDENTIALS_FILE / JARVIS_GOOGLE_TOKEN_FILE). Connect once from
Plugin Settings -> CONNECT GOOGLE ACCOUNT. Until then the email and calendar
tools stay hidden, and nothing here ever opens a browser by itself.

The leading underscore keeps the plugin loader from treating this helper as a
plugin; core/mail_calendar.py imports it to register the providers.
"""
from __future__ import annotations

import base64
from email.mime.text import MIMEText

from jarvis.core.mail_calendar import (
    CalendarProvider, MailProvider, register_calendar_provider, register_mail_provider,
)
from jarvis.plugins import _google_core as google


def _authorized() -> bool:
    return google.is_configured() and google.is_authorized()


def _header(headers: list, name: str, default: str = "") -> str:
    for row in headers or []:
        if str(row.get("name", "")).lower() == name.lower():
            return row.get("value", default)
    return default


def _plain_body(payload: dict) -> str:
    """The text/plain body of a Gmail message payload (first one found)."""
    stack = [payload or {}]
    html = ""
    while stack:
        part = stack.pop(0)
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
        if data and mime == "text/html" and not html:
            html = base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
        stack.extend(part.get("parts") or [])
    if html:
        import re
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _raw(to: str, subject: str, body: str) -> dict:
    msg = MIMEText(body or "")
    msg["to"] = to
    msg["subject"] = subject or ""
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


class GmailProvider(MailProvider):
    name = "gmail"

    def is_configured(self) -> bool:
        return _authorized()

    def _svc(self):
        return google.get_service("gmail", "v1")

    def list_messages(self, query: str = "", max_results: int = 10) -> list[dict]:
        svc = self._svc()
        resp = svc.users().messages().list(
            userId="me", q=query or "", maxResults=max(1, min(int(max_results), 25))
        ).execute()
        out = []
        for row in resp.get("messages", []) or []:
            msg = svc.users().messages().get(
                userId="me", id=row["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = msg.get("payload", {}).get("headers", [])
            out.append({
                "id": row["id"],
                "from": _header(headers, "From", "unknown"),
                "subject": _header(headers, "Subject", "(no subject)"),
                "date": _header(headers, "Date"),
                "snippet": msg.get("snippet", ""),
            })
        return out

    def read_message(self, message_id: str) -> dict:
        msg = self._svc().users().messages().get(
            userId="me", id=message_id, format="full").execute()
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        return {
            "id": message_id,
            "from": _header(headers, "From", "unknown"),
            "to": _header(headers, "To"),
            "subject": _header(headers, "Subject", "(no subject)"),
            "date": _header(headers, "Date"),
            "body": _plain_body(payload)[:8000],
        }

    def create_draft(self, to: str, subject: str, body: str) -> str:
        creds = google.get_credentials()
        if hasattr(creds, "has_scopes") and not creds.has_scopes([google.GMAIL_COMPOSE_SCOPE]):
            raise RuntimeError(
                "drafts need one more Google permission; reconnect the Google account "
                "in Plugin Settings once")
        draft = self._svc().users().drafts().create(
            userId="me", body={"message": _raw(to, subject, body)}).execute()
        return draft.get("id", "")

    def send_message(self, to: str, subject: str, body: str) -> str:
        sent = self._svc().users().messages().send(
            userId="me", body=_raw(to, subject, body)).execute()
        return sent.get("id", "")


class GoogleCalendarProvider(CalendarProvider):
    name = "google_calendar"

    def is_configured(self) -> bool:
        return _authorized()

    def _svc(self):
        return google.get_service("calendar", "v3")

    def list_events(self, days: int = 1, max_results: int = 10) -> list[dict]:
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        resp = self._svc().events().list(
            calendarId="primary", timeMin=now.isoformat(),
            timeMax=(now + dt.timedelta(days=max(1, int(days)))).isoformat(),
            maxResults=max(1, min(int(max_results), 50)),
            singleEvents=True, orderBy="startTime",
        ).execute()
        return [{
            "id": ev.get("id", ""),
            "title": ev.get("summary", "(untitled)"),
            "start": (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date", ""),
            "end": (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date", ""),
            "location": ev.get("location", ""),
        } for ev in resp.get("items", []) or []]

    def create_event(self, title: str, start_iso: str, end_iso: str,
                     description: str = "", location: str = "") -> dict:
        body = {"summary": title, "start": {"dateTime": start_iso},
                "end": {"dateTime": end_iso}}
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        ev = self._svc().events().insert(calendarId="primary", body=body).execute()
        return {"id": ev.get("id", ""), "title": title, "start": start_iso, "end": end_iso,
                "link": ev.get("htmlLink", "")}


register_mail_provider(GmailProvider())
register_calendar_provider(GoogleCalendarProvider())
