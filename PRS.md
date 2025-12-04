## pr 0 – onboarding diagnostics plumbing

### overview

- **goal**: introduce onboarding diagnostics fields into backend + frontend contracts without changing behavior.
- **type**: pure schema + plumbing; no logic change.

### scope

- **backend**:
  - add `OnboardingIssue` model in `backend/agent_types.py`:
    - **fields**: `type: str`, `severity: str`, `message: str`, `related_ids: list[str] | None`.
  - extend `AgentState`:
    - `onboarding_issues: list[OnboardingIssue] = []`
    - `onboarding_score: int | None = None`
    - `onboarding_trust: str | None = None` (e.g. `"HIGH_TRUST" | "MEDIUM_TRUST" | "LOW_TRUST"`).
  - extend `backend/server.py::AgentResponse` to include:
    - `onboarding_issues: list[dict]`
    - `onboarding_score: int | None`
    - `onboarding_trust: str | None`.
  - ensure `/api/agent` populates these with **empty/default** values only.

- **frontend**:
  - extend `AgentResponse` interface in `frontend/src/api.ts`:
    - `onboarding_issues: { type: string; severity: string; message: string; related_ids?: string[] | null; }[]`
    - `onboarding_score: number | null`
    - `onboarding_trust: string | null`.
  - do **not** render them yet.

### api / contracts

- update `backend/API_CONTRACTS.md` to document the new keys for `/api/agent`.
- update any api contract tests (`test_api_contracts.py` or similar) to include the new keys with default values.

### tests

- backend:
  - snapshot-style contract test for `/api/agent` ensuring keys are present and defaulted (e.g. `[]`, `null`).
- frontend:
  - type-checks compile; no runtime behavior change.

### non-goals

- no scoring or issue-generation logic.
- no ui changes / visualizations.


## pr 1 – solidify atomic extractors as primary building blocks

### overview

- **goal**: make `ExtractFactoryEntitiesTool`, `ExtractRoutingTool`, `ExtractParametersTool`, `ValidateFactoryTool` into a clean, end-to-end atomic pipeline that mirrors `ParseFactoryTool`.
- **type**: refactor + alignment, minimal external behavior change.

### scope

- **backend**:
  - review and tighten argument + output contracts for:
    - `ExtractFactoryEntitiesTool`
    - `ExtractRoutingTool`
    - `ExtractParametersTool`
    - `ValidateFactoryTool`
  - ensure they can be called in sequence to produce a `FactoryConfig` identical (or very close) to the existing `ParseFactoryTool` on canonical inputs.
  - refactor `ParseFactoryTool` internals to:
    - share the same underlying `onboarding.py` functions as the atomic tools, **or**
    - (optionally) call the atomic logic directly in-process (not via the agent tool registry) while keeping the same external `ParseFactoryTool` interface.

### api / contracts

- no new public fields or endpoints.
- `parse_factory` tool output schema remains the same.

### tests

- add tests that:
  - run `ParseFactoryTool` and the 4-step atomic chain on the same inputs and compare resulting `FactoryConfig`s (allowing for trivial differences like ordering if necessary).
  - cover both happy path and a few edge cases (missing durations, simple malformed input).

### non-goals

- no multi-pass logic.
- no onboarding issues or scoring yet.


## pr 2 – explicit assembler + invariant gate

### overview

- **goal**: encapsulate “entities + routing + parameters → `FactoryConfig`” as a single deterministic function, followed by the existing invariant gate.
- **type**: extraction of core logic into a named unit.

### scope

- **backend**:
  - introduce `assemble_factory(entities, routing, params) -> FactoryConfig` in `backend/onboarding.py` (or a small new module).
  - use `assemble_factory` inside:
    - `ValidateFactoryTool.execute`
    - any `ParseFactoryTool` path that previously duplicated this assembly logic.
  - ensure `validate_and_normalize(raw: RawFactoryConfig)` remains the authoritative invariant gate for llm-based pipelines.
  - consider adding docstrings that clearly state:
    - `assemble_factory` is pure and deterministic.
    - post-conditions before feeding into `validate_and_normalize`.

### api / contracts

- none.

### tests

- focused unit tests for `assemble_factory`:
  - correct handling of:
    - missing routes,
    - missing durations,
    - unknown ids in routing/parameters.
  - ensure it produces `FactoryConfig` objects that, once passed through `validate_and_normalize`, behave as expected (no silent weirdness).

### non-goals

- diagnostics and scoring still not implemented.
- still single-pass use.


## pr 3 – first diagnostics + onboarding score (single-pass)

### overview

- **goal**: start populating `onboarding_issues`, `onboarding_score`, and `onboarding_trust` for a single extraction path.
- **type**: new logic, still no multi-pass/alternatives.

### scope

- **backend**:
  - in `ParseFactoryTool.execute` (or the atomic pipeline endpoint):
    - after `FactoryConfig` is produced:
      - call `estimate_onboarding_coverage(factory_text, factory)`:
        - for each warning, create an `OnboardingIssue` with `type="coverage_miss"`, `severity="warning"`, relevant ids.
      - hook into normalization behavior:
        - any repairs (jobs dropped, durations clamped, invalid steps removed) should surface as `OnboardingIssue` with `type="normalization_repair"`.
    - attach these issues to `state.onboarding_issues`.
  - implement `compute_onboarding_score(state: AgentState) -> tuple[int, str]`:
    - simple heuristic:
      - start at 100.
      - subtract points per coverage miss.
      - subtract points per normalization repair.
    - set `state.onboarding_score` and `state.onboarding_trust` based on thresholds.

- **server / api**:
  - ensure `AgentResponse` is returning the populated issues + score.

### tests

- backend:
  - tests that:
    - known “clean” factory yields high score, no / few issues.
    - factories with missing ids or normalization repairs produce expected issue types and non-trivial score penalties.
  - check that `onboarding_trust` bands map correctly from score.

### non-goals

- no multi-pass alternative configs yet.
- no frontend usage beyond maybe logging / manual inspection.


## pr 4 – multi-pass onboarding + alternative configs + diffs (backend only)

### overview

- **goal**: introduce multi-pass extraction, alternative configs, and structural diffs; keep this internal to the backend for now.
- **type**: new orchestration + diffing logic.

### scope

- **backend**:
  - define a helper:
    - `run_onboarding_pass(factory_text: str, mode: str) -> Optional[FactoryConfig]`:
      - mode examples: `"conservative"`, `"inclusive"`, `"default"`.
      - internally uses the entity/routing/parameter extractors + assembler + invariants.
  - define `run_multi_pass_onboarding(factory_text: str) -> dict`:
    - runs K passes (K=2 or 3) with different modes/settings.
    - collects valid `FactoryConfig`s.
    - deduplicates structurally-identical configs.
    - chooses a primary config using a simple rule (e.g. first valid conservative).
    - computes structural diffs between primary and each alternative:
      - machines added/removed,
      - jobs added/removed,
      - per-job routing differences,
      - timing/due-time differences.
    - returns:
      - `primary_config`,
      - `alt_configs`,
      - `diff_summary` (compact representation suitable for later exposure),
      - `alt_conflict_issues` as `OnboardingIssue`s.
  - integrate `run_multi_pass_onboarding` into `ParseFactoryTool` or `ENSURE_FACTORY` path, but:
    - keep `state.factory` = primary config.
    - add generated `alt_conflict` issues to `state.onboarding_issues`.

### api / contracts

- for now, do **not** expose alt configs or diffs on `/api/agent`.
- only `onboarding_issues` and `onboarding_score` reflect the multi-pass effects.

### tests

- unit tests for:
  - structural diff function (machines/jobs/routing).
  - `run_multi_pass_onboarding` behavior when:
    - all passes agree,
    - passes disagree on routing,
    - one pass fails invariants while another succeeds.
- ensure appropriate `alt_conflict` issues are created when expected.

### non-goals

- no frontend changes yet.
- no sim-based impact computation.


## pr 5 – integrate onboarding diagnostics into data_flow / AgentTrace backbone

### overview

- **goal**: make onboarding stages and diagnostics visible in the data flow trace (backend side only).
- **type**: tracing + observability wiring.

### scope

- **backend**:
  - in `agent_engine` and/or tool implementations:
    - wrap each major onboarding stage with `start_data_flow_step` / `add_operation` / `finish_data_flow_step`:
      - O0: explicit id extraction.
      - O1: entity extraction.
      - O2: routing extraction.
      - O3: parameter extraction.
      - assemble + normalize.
      - multi-pass consensus / diff.
    - for diagnostics:
      - when computing coverage / normalization / alt_conflicts, add a `DataFlowStep` or `Operation` of type `VALIDATION` summarizing:
        - issue counts by type/severity.
        - onboarding score / trust band.
  - ensure these new steps are included in `state.data_flow` and therefore serialized by `/api/agent`.

### api / contracts

- `data_flow` structure stays the same; just more steps/operations.
- `OperationInfo.type` already has `"validation"` as a valid value, so reuse it.

### tests

- backend:
  - tests that:
    - for a normal run, `data_flow` contains the new onboarding steps with reasonable previews.
    - for an error run, validation steps show up and reflect issues.

### non-goals

- no changes to `_build_trace_from_state` or frontend `AgentTrace` rendering yet (beyond indirect added data).


## pr 6 – augment BriefingAgent / GenerateBriefingTool with onboarding context + questions

### overview

- **goal**: integrate onboarding diagnostics into the final markdown answer and add clarifying questions.
- **type**: prompt and context refactor; no new endpoints.

### scope

- **backend**:
  - in `GenerateBriefingTool.execute`:
    - when building `context` for `BriefingAgent.run`, append:
      - onboarding score/trust.
      - a summarized list of `OnboardingIssue`s (e.g. top N by severity).
      - (optionally) a short note about the presence of alternative configs (from `diff_summary`).
  - in `BriefingAgent` prompt:
    - extend the schema/instructions to require:
      - a `## Onboarding Issues` section summarizing the issues.
      - a `## Clarifying Questions` section with 2–5 specific questions aimed at resolving ambiguity / conflicts.
    - keep the rest of the briefing structure intact.

### api / contracts

- `/api/agent` stays the same; `final_answer` markdown becomes richer.

### tests

- backend:
  - monkeypatch `call_llm_json` to return a fixed `BriefingResponse`.
  - assert that when onboarding issues are present:
    - the generated `briefing` (or fallback) contains the expected sections.
- ensure error fallback path (deterministic template) still works and can gracefully mention that onboarding diagnostics were not available if needed.

### non-goals

- no frontend clarifications box yet.
- no change to sim integration logic.


## pr 7 – frontend: add clarifications input + onboarding summary panel

### overview

- **goal**: support the manual correction loop and visibly show onboarding score/issues.
- **type**: ui + wiring only.

### scope

- **frontend** (`App.tsx`, css):
  - add `clarifications` state (`useState<string>`).
  - render a new textarea under inputs:
    - label: “Clarifications for Next Run” (or similar).
  - change the `userRequest` composition to:

    ```text
    Factory:
    {factoryDescription}

    Clarifications:
    {clarifications}

    Situation:
    {situation}
    ```

  - add a new “Onboarding Summary” panel in the right column:
    - if `agentResult.onboarding_score` is not null:
      - show score + trust label (e.g. color-coded).
    - list `agentResult.onboarding_issues`:
      - grouped or at least styled by severity.

### api / contracts

- uses the fields introduced in pr 0/3; no new api changes.

### tests

- basic:
  - type-checks.
  - manual sanity: run app, ensure the new panel appears and data is wired.

### non-goals

- no advanced diff display.
- no changes to `AgentTrace` component yet.


## pr 8 – frontend: AgentTrace onboarding visualization

### overview

- **goal**: make `AgentTrace` explicitly show the onboarding pipeline and issues.
- **type**: purely frontend; leverages existing `trace`/`scratchpad`.

### scope

- **frontend** (`AgentTrace.tsx` + css):
  - enhance parsing of `scratchpad` lines and/or `trace` entries to:
    - detect onboarding stage markers (you may add consistent prefixes in earlier prs, e.g. `[Step X] O1: Extract entities...`).
    - distinguish:
      - normal plan execution (`Executing: simulate_baseline` etc.),
      - onboarding stages,
      - errors / issues.
  - add visual variants:
    - different badge or background for onboarding-related scratchpad items.
    - highlight lines containing known issue types (e.g. `coverage`, `normalization`, `alt_conflict`).
  - optionally show `onboarding_score` / `onboarding_trust` in the trace header when available.

### api / contracts

- none; uses existing fields.

### tests

- visual/manual check:
  - run a scenario with known onboarding issues and confirm:
    - onboarding stages and issues appear with correct styling.
- optional snapshot test for the component output if you already have testing infra.

### non-goals

- no new backend tracing fields; uses what’s already there from pr 5.


## pr 9 (optional) – expose alternative configs + diff summary to frontend

### overview

- **goal**: visibly show that multiple plausible factories were found and how they differ (structurally).
- **type**: small api extension + frontend presentation.

### scope

- **backend**:
  - extend `AgentResponse` (server + `api.ts`) with:
    - `alt_factories?: FactoryConfig[] | null` (or a reduced form: ids and names only).
    - `diff_summary?: { alt_index: number; differences: string[] }[]` (textual chewable summary).
  - when `run_multi_pass_onboarding` finds distinct configs:
    - include a compact representation in these fields.

- **frontend**:
  - add an “Alternative Interpretations” panel:
    - for each `diff_summary` entry:
      - show a label (“Alt 1”, “Alt 2”),
      - list key differences (e.g. “J3 route: M1→M2→M3 vs M1→M3”).
    - optionally allow toggling between displaying primary and an alternative config in the existing “Inferred Factory” view.

### api / contracts

- update contracts + tests:
  - document new optional fields in `API_CONTRACTS.md`.
  - extend tests to accept their presence/absence.

### tests

- backend:
  - tests that when multiple distinct configs exist, `diff_summary` is non-empty and sane.
- frontend:
  - ensure panel renders when `diff_summary` present and behaves sensibly when absent.

### non-goals

- no complex graph visualizations.
- no sim-impact comparison between configs.