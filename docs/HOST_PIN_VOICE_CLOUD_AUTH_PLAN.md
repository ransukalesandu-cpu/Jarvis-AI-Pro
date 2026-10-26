# Host PIN + Voice ID cloud authorization

## Goal
Use the existing local `AuthManager` PIN/verified-live-voice session to decide when the host may request privileged cloud access. Do not introduce email/password login for this flow.

## Trust boundaries
- PIN and voice samples/embeddings remain local.
- A local `FULL_ACCESS_MODE` state is necessary but not sufficient for cloud host privileges.
- The host device must also prove possession of a device-bound signing key whose public key is provisioned server-side.
- The server verifies the signature over the exact request body, timestamp, and one-time nonce before skipping the normal-user quota.
- Normal installs use Supabase anonymous Auth (no email/password) and server-enforced per-user quotas.
- Host requests remain subject to anti-replay and abuse protections; “unlimited” means no normal-user daily quota, not bypassing provider billing or infrastructure safeguards.

## Rollout safety
1. Keep the existing deployed function unchanged until the new source and migration are reviewed.
2. Add database quota and replay-prevention RPCs with least privilege.
3. Generate the device key locally and provision only its public key as a Supabase secret.
4. Deploy the function with JWT verification enabled; the function must still validate authenticated user identity and host signatures itself.
5. Test normal-user quota, host PIN/voice gate, invalid signature, replayed nonce, expired timestamp, and provider failure before merging.

## Important limitations
Speaker verification is not perfect liveness proof. The existing local `AuthManager` must remain the gate, and the cloud endpoint must never trust a client-supplied `host=true` flag. No PIN, voice sample, provider key, or device private key should be committed to GitHub or sent to logs.