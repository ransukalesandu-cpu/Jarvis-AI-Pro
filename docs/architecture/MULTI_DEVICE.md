# Multi-device: the dedicated worker node (Phase 1)

Owner decision (Phase 0 audit, `docs/plans/IRON_MAN_UPGRADE_PHASE0_AUDIT.md` §8): **desktop mode
stays on the laptop** (voice, HUD, approvals, computer control). A separate always-on device runs a
headless **worker node** that takes background and, from Phase 3, engineering jobs, so the laptop
does not have to. The phone stays a companion: it can see status, not send work.

```
 laptop (desktop mode)                         dedicated device
 ┌──────────────────────────────┐   HTTPS     ┌────────────────────────────────┐
 │ voice · HUD · approvals      │  + bearer   │ python -m jarvis.node serve    │
 │ core/nodes: registry,        │ ──────────▶ │ MCP over streamable HTTP       │
 │   router, remote jobs        │  (MCP)      │ ledger (leases, idempotency)   │
 │ web UI "Worker Nodes" window │ ◀────────── │ worker pool (limited children) │
 └──────────────────────────────┘             └────────────────────────────────┘
        ▲ read-only /api/nodes
   phone dashboard (owner only)
```

The existing **hub mode** (`jarvis/hub`, `jarvis/laptop_agent`) is unchanged and separate.

## Roles and permissions

| Device | Runs | Can do |
|---|---|---|
| Laptop | desktop mode + `core/nodes` client | Everything it did before; submits jobs to the node; owns approvals |
| Dedicated device | `jarvis.node` only | Runs only the job kinds in its closed registry (`jarvis/node/kinds.py`); no shell, no desktop control, no audio |
| Phone | dashboard in the browser | Owner-only read-only status (`/api/nodes`): node status, load, recent job states. Cannot submit or cancel |

Capabilities are a closed set (`jarvis/node/protocol.py`): `assistant.orchestrate`,
`engineering.cadquery`, `engineering.ngspice`, `engineering.openmodelica`, `laptop.desktop_control`,
`laptop.audio_io`, `phone.dashboard`. `laptop.*` never leaves the laptop; `sensitive` work never
leaves the laptop.

## Setting it up

### On the dedicated device

1. Clone the repository and install the minimal node dependencies (no Qt, no audio, no AI SDKs):
   ```
   python -m pip install -r jarvis/requirements-node.txt
   ```
2. Give it a private address the laptop can reach. Recommended: Tailscale on both devices, then
   `tailscale cert <device>.<tailnet>.ts.net` for a certificate.
3. Configure (environment variables; see `jarvis/node/config.py`):
   ```
   JARVIS_NODE_ID=forge
   JARVIS_NODE_CERT=/path/forge.tail1234.ts.net.crt
   JARVIS_NODE_KEY=/path/forge.tail1234.ts.net.key
   JARVIS_NODE_PUBLIC_HOST=forge.tail1234.ts.net
   ```
   Without a certificate the node listens on `127.0.0.1` only (useful to try it on one machine).
   With one, it listens on its LAN/Tailscale addresses. **Public addresses are never bound.**
4. Issue a token for the laptop. It is printed once; the node keeps only its SHA-256 hash:
   ```
   python -m jarvis.node token laptop
   ```
5. Start it: `scripts/start_node.sh` (or `scripts\start_node.cmd` on Windows). Use your OS's
   service manager (systemd, Task Scheduler) to start it at boot.

### On the laptop

1. Store the token in a user environment variable (never in a file in the repository, never in chat):
   ```
   setx JARVIS_NODE_TOKEN "<token>"
   ```
2. Add the node to `<user data>/mcp_servers.json` (on Windows `%LOCALAPPDATA%\jarvis\mcp_servers.json`):
   ```json
   {"servers": {"forge": {"url": "https://forge.tail1234.ts.net:8770/mcp",
                          "bearer_env": "JARVIS_NODE_TOKEN", "role": "worker"}}}
   ```
   `"role": "worker"` matters: worker nodes are used only through `core/nodes` (routing, policy,
   job tracking) and are **never** exposed as generic MCP tools to the model.
3. Restart JARVIS. Say *"node status"* or *"test the node"*, or open **Worker Nodes** in the web UI.

### Lost or retired device

On the node: `python -m jarvis.node revoke laptop` (or `rotate laptop` to issue a fresh token). The
running node re-reads its token file on every request, so the revoked token is refused immediately.

## How a job runs

1. **Placement** (`core/nodes/router.py`): capability → healthy node → headroom (queue below
   `max_parallel × 4`, at least 256 MB free) → most free memory → shortest queue. If no node can
   take it, the job is **blocked with the real reason**. Engineering work never falls back to the
   laptop; other work may run on the laptop only if the owner agrees each time (wired per job type
   in later phases — Phase 1 has no laptop fallback).
2. **Submit** (`core/nodes/jobs.py`): the submission and its idempotency key are saved *before*
   sending. If the reply is lost, the retry reuses the key and the node returns the job it already
   has — never a second copy.
3. **Run** (`jarvis/node/worker.py`): the node claims the job under a **lease** (holder, epoch,
   expiry), runs it in a child process (`python -I`, scrubbed environment, own work folder,
   wall-clock/memory/output limits from `core/sandbox.py`) and renews the lease while it runs.
4. **Follow**: the laptop polls status. While the node is unreachable the job shows
   **waiting for node**, never failed or done. A status must name the same job and node and its
   lease epoch may never go backwards, so stale or foreign answers are ignored.
5. **Cancel**: "cancel job …", the HUD stop button, the stop word and the emergency stop send
   `job_cancel`. The node kills the child at its next lease renewal (≤ 5 s). Success is reported only
   when the node confirms.
6. **Restart**: a node restart re-queues an idempotent job (new epoch, attempt counted) and marks a
   non-idempotent one *interrupted* — it is never re-run silently. A laptop restart re-checks saved
   submissions; nothing is re-sent under a new key.

Every remote job is an ordinary JARVIS background job, so it appears in the Jobs window and is
announced when it ends. Hook events: `node_online`, `node_offline`, `node_job_finished`.

## Security model

| Layer | Rule |
|---|---|
| Network | Public addresses never bound; public peers refused before auth (`hub/netbind.py`); TLS required off loopback |
| Identity | One token per device, `controller` role, SHA-256 hash only on the node; revocation effective on the next request; 10 failed attempts per minute per address are throttled |
| Host header | MCP SDK DNS-rebinding protection: only loopback, the bound addresses and `JARVIS_NODE_PUBLIC_HOST` |
| Requests | Closed, versioned schemas; unknown fields refused; payload ≤ 64 KB; kinds from a closed registry; per-device scoping of every job |
| Execution | Child process, no inherited secrets, limits on time, memory and output. **Not network-isolated yet**: Phase 1's diagnostic kinds make no network calls, but the OS does not stop a child from doing so. Engineering workers (Phase 3) must add OS-level isolation (e.g. a no-network user/namespace on Linux) before they run model-derived specs |
| Secrets | Tokens never in logs, ledgers, submissions, UI events or the phone API (covered by tests) |
| Laptop | Generic `mcp` tool cannot reach a worker; `node_status` is SAFE (read-only), `node_test` is SENSITIVE (owner must be verified); node jobs are excluded from the task planner |

## Measurements (Linux sandbox, Python 3.13 — not the owner's laptop)

| What | Result |
|---|---|
| Laptop, no node configured | +0.5 MB RSS, no extra threads |
| Laptop, one node configured (client + heartbeat) | +12 MB RSS; heartbeat CPU 0.033 % of one core over 60 s |
| Diagnostic job round trip on loopback | 0.23 s |
| Node process (server + ledger + worker, idle) | ~64 MB peak RSS; no Qt / audio / AI SDK imported |

Phase 1 offloads only diagnostic jobs, so it does **not** yet reduce the laptop's load; it adds the
small client cost above. The reduction comes with the first real offloaded workloads (Phase 2
background tasks, Phase 3 engineering), measured with `python -m jarvis.tools.profile_ram`.

## What the owner must verify (cannot be tested here)

1. Node on the real dedicated device with a Tailscale certificate; laptop reaching it over the tailnet.
2. Windows: `setx` token, `mcp_servers.json` entry, "node status" and "test the node" by voice; the
   Worker Nodes window in `JARVIS_UI=web`; cancel from the Jobs window.
3. Phone: the node pill in the dashboard header (owner-verified session).
4. Pull the node's network cable during "test the node for 60 seconds": the job must show waiting,
   then finish after reconnecting, with one job on the node.
5. `python -m jarvis.node revoke laptop`: the laptop must show the node as offline/refused at the
   next heartbeat.
