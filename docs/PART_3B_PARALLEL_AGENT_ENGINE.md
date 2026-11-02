# Part 3B — Bounded Parallel Agent Engine

Part 3B upgrades the existing task runner with a reusable, bounded worker engine.
It does not create multiple autonomous task owners or bypass the existing
planner, policy engine, authorization checks, persistence, or approval flow.

## Execution model

1. Part 3A validates and topologically orders the task dependency graph.
2. The runner identifies a safe batch of ready, independent file-read steps.
3. A bounded worker pool executes the batch concurrently.
4. Results are collected and committed to the task journal in original plan order.
5. The main scheduler resumes dependency evaluation and runs the next eligible
   step or batch.

## Parallelism contract

- Only non-consequential READ_FILE steps are eligible for parallel execution.
- All declared dependencies must already be completed before a step is dispatched.
- A dependency-waiting read may be skipped while later independent reads in the
  same read-only segment proceed.
- A write, shell command, browser action, screen action, or consequential step is
  an ordering barrier. Reads are never speculatively scheduled across it.
- Worker count is configurable and clamped to 1–4; the default remains small to
  protect low-memory laptops.
- Results are returned in plan order regardless of completion order.
- Exceptions are isolated per step and represented as normal step failures.

## Cancellation and shared state

- Once cancellation is observed, no additional queued work is dispatched.
- Already-running workers receive the shared cancellation event and are allowed
  to finish cooperatively; their completed results are preserved.
- Unstarted work is recorded as cancelled/skipped by the runner.
- Step state transitions, task checkpoints, worker journal events, and progress
  throttling are serialized with the runner lock.
- The worker pool is scoped to a batch and shuts down after the batch; there is
  no always-on pool or new third-party dependency.

## Security and compatibility

- Every step still passes through PolicyEngine, owner revalidation, Privacy
  Lock checks, and the existing approval callback.
- No shell, write, browser, or desktop-control operation is newly parallelized.
- Browser automation remains on its existing thread-affine worker.
- Task storage, event contracts, voice commands, and UI integration remain
  backward-compatible.

## Validation

Regression coverage includes worker-cap enforcement, deterministic result
ordering, exception isolation, cancellation-aware dispatch, dependency-aware
ready-read scheduling, and preservation of the existing task runner behavior.
CI must pass on the latest PR head before Part 3B is considered complete.
