# Repair a broken local JARVIS memory audit chain

Use this only if JARVIS reports that `Memory audit history is invalid` or a `broken link` and cannot save new memories.

1. Close JARVIS completely.
2. Open the `JarvisAI` folder from the extracted project.
3. Double-click `Repair_Memory_Audit.bat` and read the warning. Press Enter only if you want to proceed.
4. The utility makes a timestamped backup under `JarvisAI/memory/audit-recovery-backups/`, re-signs the retained audit rows, records an `audit_chain_recovered` event, and verifies the new chain.
5. Launch JARVIS again and test saving a memory.

**Integrity note:** re-signing cannot retroactively prove the old broken history was authentic. The original local database/JSON and audit key/checkpoint are preserved in the backup directory for investigation or restoration. If the signing key is missing or truncated while signed history exists, the tool refuses automatic recovery rather than inventing a new trust history.

Do not run the recovery utility while JARVIS is open. Do not share the backup directory publicly; it can contain personal memories.
