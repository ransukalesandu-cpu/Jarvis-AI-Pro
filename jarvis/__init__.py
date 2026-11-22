"""JARVIS AI — a local-first voice assistant with a holographic desktop UI."""

__version__ = "1.0.0"

# These run as the package loads, before any third-party SDK is imported:
#  1. a local untracked .env (if any) fills in missing environment variables,
#     so keys can live there instead of in config/api_keys.json;
#  2. telemetry opt-outs and the OFFLINE=1 kill switch are applied;
#  3. existing credential files are tightened to owner-only permissions.
from jarvis.core import local_env as _local_env
from jarvis.core import privacy as _privacy
from jarvis.core import secure_file as _secure_file

_local_env.load()
_privacy.apply()
for _name in ("api_keys.json", "google_token.json", "google_credentials.json"):
    _secure_file.restrict_permissions(_secure_file.Path(__file__).resolve().parent / "config" / _name)
del _name
