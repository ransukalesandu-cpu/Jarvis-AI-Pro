# Part 3A — Intelligent Brain & Task Planning

Part 3A strengthens the existing autonomous task planner without introducing a
second agent runtime or changing the application's voice, UI, cloud store, or
owner-security integrations.

## Planning flow

1. Normalize and validate the user's objective.
2. Ask the existing configured planning provider for a bounded JSON plan.
3. Validate typed tools, required inputs, workspace paths, command lengths,
   step count, and checkpoint size.
4. Validate the dependency graph and reject missing references, self-dependencies,
   and cycles.
5. Apply a stable topological order and remap dependency indexes.
6. Fall back to the deterministic planner when the planning provider fails.
7. Pass the validated plan to the existing TaskRunner and policy checks.

## Dependency graph contract

depends_on contains zero-based indexes into the model's original steps array.
Forward references are supported. The planner drops malformed steps and any
steps that depend on removed steps; invalid indexes and cycles reject the plan.
Independent steps retain their relative order. The resulting plan is always
topologically ordered before it reaches task execution.

Task.set_plan() repeats graph validation at the task boundary so callers other
than the model planner cannot inject an invalid graph.

## Tool selection and deterministic fallback

The model prompt directs the planner to choose the narrowest typed tool, split
complex work into independently verifiable steps, and express only real
dependencies. Existing browser actions remain read-only. Repository changes
must include a test or verification step. The deterministic planner recognizes
public-web research intents without requiring a planning API key; it reports
retrieved evidence rather than pretending to perform model-based analysis.

## Bounds and security

- Existing maximum step count and cloud checkpoint size remain enforced.
- Commands and file paths retain existing validation.
- The planner cannot grant authorization by setting consequential.
- Execution still passes through PolicyEngine, owner revalidation, Privacy
  Lock, and the existing approval callback.
- Browser steps remain read-only and subject to network policy.
- No new third-party dependency or always-on worker is introduced.

## Validation

The regression suite covers stable topological ordering, forward dependencies,
dependency remapping, cycles, self-dependencies, missing indexes, planner
parsing, and deterministic research intent routing. CI must pass on the PR head
before Part 3A is considered merged. Live provider behavior and Windows device
behavior still require runtime testing in the user's environment.
