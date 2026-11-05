"""Task orchestration for computer control (Project 2, inspired by Microsoft UFO²).

UFO² splits work between a HostAgent (understands the request, decomposes it,
picks applications) and per-application AppAgents (act inside one app with UIA
and app APIs), with a shared blackboard and per-step verification. JARVIS keeps
that shape but none of UFO's code or framework:

* :mod:`plan`    — validated steps (tool + args + dependencies + expectation),
                   ordered with ``agent/dependency_graph.topological_sort_steps``;
* :mod:`planner` — decomposition: a deterministic planner for common requests
                   and an optional cloud planner (existing HybridLLMRouter, redacted);
* :mod:`agents`  — the agent registry: which application agent owns which tools;
* :mod:`host`    — the Host Agent: shared task context, execution trace,
                   bounded recovery, final verification, honest report;
* :mod:`jobs`    — every task runs as a ``JobManager`` job (Jobs window, Cancel,
                   Island chip, completion notice) and publishes status on the StateBus.
"""
