"""Supabase Edge Function transport with anonymous auth and optional host signing.

The desktop stores only public Supabase configuration and an anonymous Auth session.
Provider API keys stay server-side. Host signatures are emitted only while the local
JARVIS owner session is verified; all other users are subject to server-side quotas.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_SESSION_FILE = Path(__file__).resolve().parent.parent / "config" / "supabase_auth_refresh.dat"
_SESSION_BLOCKED_FILE = _SESSION_FILE.with_suffix(".blocked")


_KEYRING_SERVICE = "JarvisAI.SupabaseAuth"
_KEYRING_ACCOUNT = "anonymous-refresh-token"


def _native_keyring():
    """Use only OS credential stores; never accept plaintext/file/fail backends."""
    import keyring

    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring as NativeKeyring
    elif sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring as NativeKeyring
    else:
        raise RuntimeError("No supported native credential store is available")
    if not isinstance(keyring.get_keyring(), NativeKeyring):
        raise RuntimeError("Supabase session persistence requires the native OS credential store")
    return keyring


def _load_persisted_refresh_token() -> str:
    """Load the anonymous Auth refresh token from DPAPI or the native OS keyring."""
    try:
        if sys.platform == "win32":
            from security.auth_manager import _dpapi_unprotect
            return _dpapi_unprotect(_SESSION_FILE.read_bytes()).decode("utf-8").strip()
        keyring = _native_keyring()
        return str(keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT) or "").strip()
    except Exception:
        return ""


def _persist_refresh_token(token: str) -> None:
    """Persist only encrypted DPAPI bytes or a native macOS/Linux credential."""
    if not token:
        return
    if sys.platform == "win32":
        from security.auth_manager import _dpapi_protect
        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = _SESSION_FILE.with_suffix(".tmp")
        try:
            temp.write_bytes(_dpapi_protect(token.encode("utf-8")))
            os.replace(temp, _SESSION_FILE)
        finally:
            temp.unlink(missing_ok=True)
        return

    keyring = _native_keyring()
    keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, token)
    if keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT) != token:
        raise RuntimeError("The OS credential store did not persist the Supabase session")


_AUTH_LOCK = threading.RLock()
_AUTH: dict[str, Any] = {
    "access_token": "", "refresh_token": "", "expires_at": 0.0, "refresh_failed": False
}


def _refresh_failure_marked() -> bool:
    """Fail closed when a prior refresh failure blocked automatic identity replacement."""
    try:
        _SESSION_BLOCKED_FILE.stat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _mark_refresh_failure() -> None:
    """Persist a non-secret block marker so a restart cannot silently create a new identity."""
    _SESSION_BLOCKED_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = _SESSION_BLOCKED_FILE.with_name(_SESSION_BLOCKED_FILE.name + ".tmp")
    try:
        temp.write_text("refresh_failed\n", encoding="ascii")
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, _SESSION_BLOCKED_FILE)
    finally:
        temp.unlink(missing_ok=True)


def _clear_refresh_failure_marker() -> None:
    """Remove the fail-closed marker only after a successful session acquisition."""
    _SESSION_BLOCKED_FILE.unlink(missing_ok=True)


def _is_transient_refresh_failure(error: RuntimeError) -> bool:
    """Keep a retryable token only for network failures and retryable HTTP statuses."""
    message = str(error).casefold()
    if any(f"http {status}" in message for status in (408, 425, 429, *range(500, 600))):
        return True
    return any(marker in message for marker in (
        "urlerror", "timeouterror", "connectionerror", "connection reset",
        "temporarily unavailable", "temporary failure", "network is unreachable",
    ))


def reset_supabase_auth_session() -> None:
    """Explicitly clear the failed session before a user-approved host re-enrollment.

    Callers must put this behind an explicit owner-confirmed reset flow. It is
    intentionally never invoked automatically after a refresh failure.
    """
    with _AUTH_LOCK:
        try:
            _SESSION_FILE.unlink(missing_ok=True)
            _SESSION_BLOCKED_FILE.unlink(missing_ok=True)
        except OSError:
            raise RuntimeError("Could not reset the Supabase Auth session safely") from None
        _AUTH.update({
            "access_token": "", "refresh_token": "", "expires_at": 0.0,
            "refresh_failed": False,
        })


def _request_json(
    url: str, *, method: str = "POST", headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None, timeout: float = 20.0,
) -> dict[str, Any]:
    data = json.dumps(body if body is not None else {}, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Supabase request failed with HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Supabase request failed ({type(exc).__name__})") from None
    if not isinstance(decoded, dict):
        raise RuntimeError("Supabase returned an invalid response")
    return decoded


def _get_access_token(base_url: str, public_key: str, timeout: float) -> str:
    now = time.monotonic()
    with _AUTH_LOCK:
        if _AUTH.get("access_token") and now < float(_AUTH.get("expires_at", 0)) - 60:
            return str(_AUTH["access_token"])

        headers = {"Content-Type": "application/json", "apikey": public_key}
        refresh = str(_AUTH.get("refresh_token") or "").strip() or _load_persisted_refresh_token()
        if not refresh and (_AUTH.get("refresh_failed") or _refresh_failure_marked()):
            raise RuntimeError(
                "Supabase session refresh is blocked; explicitly reset/re-enroll the host session before creating a new identity"
            ) from None
        auth_result: dict[str, Any] | None = None
        if refresh:
            try:
                auth_result = _request_json(
                    base_url + "/auth/v1/token?grant_type=refresh_token",
                    headers=headers, body={"refresh_token": refresh}, timeout=timeout,
                )
            except RuntimeError as exc:
                # Never replace the Auth identity automatically. Retry a saved token
                # only for classified transient transport/server failures; permanent
                # refresh failures require an explicit owner-approved session reset.
                retryable = _is_transient_refresh_failure(exc)
                _AUTH.update({
                    "access_token": "",
                    "refresh_token": refresh if retryable else "",
                    "expires_at": 0.0,
                    "refresh_failed": True,
                })
                try:
                    _mark_refresh_failure()
                except OSError:
                    raise RuntimeError(
                        "Supabase refresh failed and the block marker could not be saved; fix local storage before restarting"
                    ) from None
                raise RuntimeError(
                    "Supabase session refresh failed; retry connectivity or explicitly reset/re-enroll the host session"
                ) from None

        if auth_result is None:
            # Supabase anonymous sign-in; no email or password is collected/stored.
            auth_result = _request_json(
                base_url + "/auth/v1/signup",
                headers=headers, body={}, timeout=timeout,
            )

        access = str(auth_result.get("access_token") or "").strip()
        refresh_token = str(auth_result.get("refresh_token") or "").strip()
        expires_in = max(60, int(auth_result.get("expires_in") or 3600))
        if not access:
            raise RuntimeError("Supabase anonymous sign-in did not return an access token")
        try:
            _clear_refresh_failure_marker()
        except OSError:
            _AUTH.update({
                "access_token": "", "refresh_token": refresh_token,
                "expires_at": 0.0, "refresh_failed": True,
            })
            raise RuntimeError("Could not clear the Supabase session block marker safely") from None
        _AUTH.update({
            "access_token": access,
            "refresh_token": refresh_token,
            "expires_at": time.monotonic() + expires_in,
            "refresh_failed": False,
        })
        if refresh_token:
            try:
                _persist_refresh_token(refresh_token)
            except Exception:
                # Fail closed on Windows rather than silently losing the stable
                # Auth identity needed to recognize the enrolled host next launch.
                if sys.platform == "win32":
                    _AUTH.update({
                        "access_token": "", "refresh_token": "", "expires_at": 0.0,
                        "refresh_failed": True,
                    })
                    try:
                        _mark_refresh_failure()
                    except OSError:
                        pass
                    raise RuntimeError("Could not securely persist the Supabase Auth session; automatic re-enrollment is blocked") from None
        return access


def has_persistent_auth_session() -> bool:
    """Return whether the active Supabase refresh token is securely persisted."""
    try:
        current = str(_AUTH.get("refresh_token") or "").strip()
        persisted = _load_persisted_refresh_token()
        return bool(current and persisted and secrets.compare_digest(current, persisted))
    except Exception:
        return False


def _local_owner_session_verified() -> bool:
    try:
        from security.auth_manager import FULL_ACCESS_MODE
        from core.security import get_auth_manager
        from security.host_cloud_access import host_session_verified
        manager = get_auth_manager()
        return bool(manager and manager.get_state() == FULL_ACCESS_MODE and host_session_verified(manager))
    except Exception:
        return False


def call_supabase_provider(
    *, provider: str, prompt: str, system_prompt: str,
    timeout: float = 20.0, model: str | None = None,
) -> dict[str, str]:
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    public_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not base_url or not public_key:
        raise RuntimeError("Supabase cloud configuration is incomplete")

    access_token = _get_access_token(base_url, public_key, timeout)
    payload: dict[str, Any] = {
        "provider": "anthropic" if provider == "claude" else provider,
        "prompt": prompt,
        "system_prompt": system_prompt,
    }
    if model:
        payload["model"] = model

    # Sign exactly the bytes sent. Host signatures are never emitted unless the
    # app's existing local owner session is already verified.
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "apikey": public_key,
        "Authorization": "Bearer " + access_token,
        # Normal users also send a unique nonce so the server can reject exact replays.
        "X-Jarvis-Host-Timestamp": str(int(time.time())),
        "X-Jarvis-Host-Nonce": secrets.token_urlsafe(24),
    }
    if _local_owner_session_verified():
        try:
            from security.host_device_identity import public_key_b64, sign_request
            headers.update(sign_request(body_bytes))
            headers["X-Jarvis-Host-Key"] = public_key_b64()
            enrollment_token = os.getenv("JARVIS_HOST_ENROLLMENT_TOKEN", "").strip()
            if enrollment_token:
                headers["X-Jarvis-Host-Enrollment"] = enrollment_token
        except Exception as exc:
            raise RuntimeError("Host cloud authentication could not sign the request") from None

    # Keep request signing and body bytes in sync; _request_json accepts dictionaries,
    # so use a dedicated byte-preserving request for the signed cloud call.
    request = urllib.request.Request(
        base_url + "/functions/v1/jarvis-cloud-ai",
        data=body_bytes,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Supabase cloud request failed with HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Supabase cloud request failed ({type(exc).__name__})") from None
    if not isinstance(result, dict):
        raise RuntimeError("Supabase cloud provider returned an invalid response")
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Supabase cloud provider returned no text")
    return {"text": text.strip(), "model": str(result.get("model") or "")}
