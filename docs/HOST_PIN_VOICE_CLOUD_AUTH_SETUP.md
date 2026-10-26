# JARVIS Host PIN + Voice Cloud Authentication

## Current implementation contract

- Local PIN/voice authentication remains authoritative for owner-only actions.
- Supabase anonymous Auth is used for cloud requests; no email/password is required.
- The Edge Function must validate the caller with Supabase Auth, not trust decoded JWT claims alone.
- Host requests are signed with an Ed25519 device key. On Windows, the private key is protected with DPAPI.
- The server stores only the registered public key. A one-time enrollment token is required for first registration.
- Host signatures cover the exact JSON request bytes, a timestamp, a fresh nonce, and the SHA-256 digest.
- Replay nonces are stored server-side and consumed atomically.
- Ordinary anonymous users are limited server-side to 100 cloud requests per UTC day. Provider billing limits still apply to all users.

## Required Supabase configuration before deployment

1. Review the SQL migration at supabase/migrations/202610260001_jarvis_host_cloud_security.sql and apply it to the intended project.
2. Configure Edge Function secrets for SUPABASE_SERVICE_ROLE_KEY, JARVIS_HOST_ENROLLMENT_TOKEN, and the provider API keys that the project actually uses. Never place the service-role key or provider keys in the desktop app or GitHub.
3. Keep the Edge Function gateway JWT verification enabled (verify_jwt: true).
4. Enable Supabase anonymous sign-ins in Auth settings. Apply appropriate CAPTCHA/rate limits if the project is exposed publicly.
5. Configure SUPABASE_URL and SUPABASE_ANON_KEY locally. For the first owner-device enrollment only, provide the same enrollment token locally; remove it from the local environment after enrollment.
6. Confirm the local JARVIS owner session is active before host requests are signed. A signed device key is not a replacement for local PIN/voice authentication.

## Validation checklist

- Anonymous sign-in succeeds with no SUPABASE_EMAIL or SUPABASE_PASSWORD values.
- Missing/expired/invalid JWT is rejected.
- Host signature with altered body, wrong key, stale timestamp, or malformed signature is rejected.
- A nonce can be consumed once only; a replay returns HTTP 409.
- Normal users receive HTTP 429 after the configured daily quota.
- Revoked or mismatched host keys are rejected.
- Provider API keys never appear in client responses or logs.
- The SQL migration, Edge Function tests, Python tests, and CI all pass before deployment.
- After deployment, verify the deployed function version and verify_jwt setting; do not infer deployment from a Git commit.

## Public credential exposure

A .env file was tracked in the repository history and included provider credential fields. Removing it from the working tree does not remove historical copies. Treat any real values that were committed as exposed: rotate the provider keys, invalidate any other exposed credentials, and check GitHub history before reusing them. Do not paste secrets into issues or pull requests.
