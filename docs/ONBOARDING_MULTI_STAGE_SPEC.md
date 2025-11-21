# Multi-Stage Constrained Extraction for Onboarding

## Overview

This system transforms free-text factory descriptions into a strict `FactoryConfig` via multi-stage GPT-4.1 extraction, with hard-fail guarantees on coverage and invariant violations.

**In scope (Phase 1):** Improve onboarding logic internally by orchestrating five pure stages. Detect explicitly mentioned IDs via regex; extract machines and jobs via two focused LLM calls; normalize and validate; enforce coverage (100% or fail). **HTTP contracts unchanged.** Implementation fits in ~1 hour.

**Key guarantee:** If text declares "M1, M2, M3" and "J1, J2, J3", the system either extracts all six and returns a `FactoryConfig`, or returns an internal error with coverage details. Coverage enforcement is 100% or hard-fail.

---

## Architecture

### Data Flow

The system runs five sequential stages, with explicit types at each boundary:

**Stage 0: Preprocessing & ID Harvesting**
- Input: `factory_text: str`
- Output: `PreparsedIds` = `{machine_ids: set[str], job_ids: set[str]}`
- Method: Deterministic regex extraction (existing `extract_explicit_ids()`)
- Purpose: Identify all explicitly mentioned machine and job IDs as reference targets for later validation

**Stage 1: Coarse LLM Extraction (Machines + Jobs Skeleton)**
- Input: `factory_text`, `PreparsedIds`
- Output: `CoarseStructure` = `{machines: list[{id, name}], jobs: list[{id, name}]}`
- Method: Single focused LLM call via `call_llm_json(prompt, CoarseStructure)`
- Purpose: Robustly extract machine and job IDs + names without steps/durations
- LLM constraint: "MUST include all IDs from PreparsedIds; MAY add inferred entities"

**Stage 2: Fine LLM Extraction (Steps & Durations)**
- Input: `factory_text`, `CoarseStructure`
- Output: `RawFactoryConfig` (shape-compatible with `FactoryConfig` but pre-normalization)
- Method: Single LLM call focused on steps, durations, due times only
- Purpose: Attach routing and timing to jobs from Stage 1
- LLM constraint: "Reference only jobs/machines from Stage 1; preserve job/machine count"

**Stage 3: Normalization & Invariants**
- Input: `RawFactoryConfig`
- Output: `FactoryConfig` or raise exception (caught by stage 4)
- Method: Call existing `normalize_factory()` + invariant checks
- Purpose: Repair durations, validate machine references, drop invalid steps, reject if jobs are lost
- Hard-fail: If normalization drops jobs, raise exception (don't silently degrade)

**Stage 4: Coverage & Decision (Only Coverage Enforcement)**
- Input: `PreparsedIds`, `FactoryConfig` (from stage 3)
- Output: `FactoryConfig` or raise `ExtractionError` (internal, not exposed to HTTP)
- Method: Compare harvested IDs vs final parsed IDs; compute coverage ratio
- Purpose: Enforce 100% coverage or hard-fail; no other validation happens here
- Hard-fail: If coverage < 100%, raise `ExtractionError` with missing IDs and ratios

### Components

**`extract_explicit_ids(factory_text: str) -> PreparsedIds`**
- Responsibilities:
  - Regex-extract all M\[0-9\]\[A-Za-z0-9_\]* and J\[0-9\]\[A-Za-z0-9_\]* patterns
  - Return unordered set of machine IDs and job IDs
  - Zero inference; pure pattern matching
- Does NOT:
  - Call LLM
  - Validate machine/job existence or structure
  - Make assumptions about names or relationships

**`extract_coarse_structure(factory_text: str, ids: PreparsedIds) -> CoarseStructure`**
- Responsibilities:
  - Build stage-1 prompt with explicit ID list
  - Call `call_llm_json(prompt, CoarseStructure)` to extract machines and jobs
  - Return machines and jobs with IDs and names only
- Does NOT:
  - Extract steps or durations
  - Validate coverage (handled in stage 4)
  - Normalize or repair data
  - Make decisions about failures

**`extract_steps(factory_text: str, skeleton: CoarseStructure) -> RawFactoryConfig`**
- Responsibilities:
  - Build stage-2 prompt with job/machine references from skeleton
  - Call `call_llm_json(prompt, RawFactoryConfig)` to extract steps, durations, due times
  - Return jobs with steps attached
- Does NOT:
  - Normalize durations or due times
  - Filter invalid steps
  - Validate coverage (handled in stage 4)

**`validate_and_normalize(raw_factory: RawFactoryConfig) -> FactoryConfig`**
- Responsibilities:
  - Call existing `normalize_factory(raw_factory)` to repair and validate
  - Check that no jobs were dropped during normalization (raise if any lost)
  - Verify all step machine_ids exist in machines list
  - Return normalized config
- Does NOT:
  - Make coverage decisions (stage 4 only)
  - Fall back to toy factory
  - Drop jobs due to coverage issues

**`assess_coverage(ids: PreparsedIds, factory: FactoryConfig) -> {machine_coverage: float, job_coverage: float, missing_machines: set, missing_jobs: set}`**
- Responsibilities:
  - Compare detected IDs vs parsed IDs (machines and jobs)
  - Compute coverage ratio: |parsed ∩ detected| / |detected|
  - Return coverage metrics and missing ID sets
  - Pure function; no side effects
- Does NOT:
  - Make decisions
  - Call LLM
  - Log (caller decides)

**`OnboardingAgent.run(factory_text: str) -> FactoryConfig`** (refactored orchestration)
- Responsibilities:
  - Orchestrate stages 0–4 in sequence: extract IDs → coarse → fine → normalize → assess coverage
  - Catch any exception (LLM failure, JSON mismatch, coverage failure, normalization failure) and raise `ExtractionError` with details
  - Log critical stages: IDs detected, coarse counts, fine counts, coverage report
  - Return `FactoryConfig` on success, raise `ExtractionError` on any failure
- Does NOT:
  - Fall back to toy factory
  - Change return type or HTTP envelope

---

## Implementation Plan

### Phase 1 (1-Hour Implementation)

**Create/refactor these components:**

1. Define DTOs: `PreparsedIds`, `CoarseStructure`, `RawFactoryConfig` (simple pydantic models only)
2. Implement `extract_explicit_ids(factory_text)` (already exists, verify regex patterns)
3. Implement `extract_coarse_structure(factory_text, ids)` with stage-1 LLM call
4. Implement `extract_steps(factory_text, coarse)` with stage-2 LLM call
5. Implement `validate_and_normalize(raw_factory)` wrapping existing `normalize_factory()`
6. Implement `assess_coverage(ids, factory)` as pure function
7. Refactor `OnboardingAgent.run(factory_text)` to orchestrate 0→1→2→3→4, raising `ExtractionError` on any failure
8. Add 3 integration tests (mocked LLM): canonical success, coverage mismatch, LLM failure

**Out of scope for Phase 1:**
- HTTP contract changes (keep `/api/onboard` exactly as today)
- Schema changes (`FactoryConfig`, `Machine`, `Job`, `Step` untouched)
- Change `/api/simulate` behavior (untouched)
- Cross-checker model, retry loops, fuzzy coverage thresholds
- Frontend error enumerations (internal `ExtractionError` only)

---

## Quality & Correctness Bar

### Success Criteria

**Coverage (Non-Negotiable):**
- If text contains explicit `M[0-9]+` or `J[0-9]+` tokens, then on success:
  - All detected IDs appear in `FactoryConfig` (machines and jobs lists)
  - No extra IDs appear that weren't detected in text
  - Coverage ratio = 100% for both machines and jobs

**Structure (Non-Negotiable):**
- Every job has ≥ 1 step
- Each step references a machine in `machines`
- Durations are integers ≥ 1; due_time_hour is integer 0–24
- No duplicate machine or job IDs

**Error Handling (Non-Negotiable):**
- Any LLM failure or schema-parse error → raise `ExtractionError` with specific code, never silent toy fallback
- Missing IDs vs text → raise `ExtractionError` with details (not best-effort degradation)
- Unresolved structure (e.g., steps referencing non-existent machines) → raise `ExtractionError` after normalization

**Developer Experience:**
- New engineer can understand pipeline by reading spec + module in < 15 minutes
- Each stage has a clear, single responsibility
- LLM calls isolated so they are easy to mock in tests
- Error messages include actionable details (which IDs missing, coverage ratios, etc.)

### Failure Behavior

**Hard Fails (Raise `ExtractionError`):**
- Coverage < 100% on any ID type (machines or jobs)
- Unresolved machine references in steps
- Jobs lost during normalization
- LLM call throws exception
- LLM returns invalid JSON (schema mismatch)
- Text contains no machines or no jobs (detected IDs empty)

**No Degraded Output:**
- System never returns a `FactoryConfig` with coverage < 100%
- System never silently drops detected IDs
- System never invents entities not mentioned in text
- System never returns toy factory from onboarding path

### Minimal Eval Set

**Case 1: Clean Canonical (Success, 100% Coverage)**
- Description: 3 machines (M1, M2, M3), 4 jobs (J1, J2, J3, J4), all explicit steps
- Text: "We have 3 machines: M1 (assembly), M2 (drill), M3 (pack). J1, J2, J3, J4 each pass through them in sequence..."
- Expected: ✓ Success, 3 machines, 4 jobs, coverage 100%

**Case 2: Coverage Mismatch (Failure)**
- Description: Text mentions M1, M2, M3, M4 but LLM only extracts M1, M2, M3
- Text: "We run 4 machines: M1, M2, M3, M4. J1 and J2 use them..."
- Expected: ✗ `COVERAGE_MISMATCH`, missing ["M4"], coverage 75%

**Case 3: Contradictory Routing (Success, Requires Explicit Steps)**
- Description: Narrative says "all jobs use M1→M2→M3" but explicit steps show J1 uses M1→M2→M4
- Text: "Jobs pass through M1, M2, M3 in sequence. J1 uses M1, M2, M4 (not M3)..."
- Expected: ✓ Success, J1 has steps [M1, M2, M4], all 4 machines preserved

**Case 4: Invalid Normalization (Failure)**
- Description: J1 has steps on M1, M5 but only M1 exists; normalization drops M5 step, leaving J1 with 1 step (OK)
- Text: "M1 only. J1 does 2h on M1, 3h on M5."
- Expected: ✗ `INVALID_STRUCTURE`, M5 not declared, coverage < 100%

**Case 5: Empty or Ambiguous (Failure)**
- Description: Text has no explicit machine IDs
- Text: "We do stuff with machines and jobs."
- Expected: ✗ `COVERAGE_MISMATCH`, no machines detected, coverage undefined (error)

---

## Tests

**Minimum test coverage for Phase 1:**

1. **Unit tests (no mocks):**
   - `test_extract_explicit_ids()`: Verify M1, M_ASSEMBLY, J1 patterns; avoid false positives
   - `test_assess_coverage()`: Known inputs → expected coverage ratios and missing ID sets

2. **Integration tests (mocked LLM):**
   - `test_onboarding_success_canonical()`: Mock LLM returns valid JSON → `FactoryConfig`
   - `test_onboarding_coverage_mismatch()`: Mock LLM returns fewer IDs → `ExtractionError`
   - `test_onboarding_llm_failure()`: Mock LLM raises exception → `ExtractionError`

3. **Real-LLM tests:** Run separately via `backend/eval/run_adversarial.py` with `--use-llm` flag; not part of default `pytest`.

---

## Observability (Minimal Critical Logging)

Log only these four points per onboarding request:

1. **Stage 0 (IDs):** `detected_machines={...}, detected_jobs={...}`
2. **Stage 1 (Coarse):** `extracted_machines_count=N, extracted_jobs_count=N`
3. **Stage 2 (Fine):** `jobs_with_steps=N, final_job_count=N`
4. **Stage 4 (Coverage):** `machine_coverage=X%, job_coverage=Y%, missing_machines={...}, missing_jobs={...}`

Do NOT log full text, full JSON payloads, or intermediate repair details.

---

## HTTP Contract (Phase 1: Unchanged)

The `/api/onboard` and `/api/simulate` HTTP contracts remain **exactly as today**. Phase 1 improves internal logic only; no HTTP envelope changes.

Internally, `OnboardingAgent.run()` will raise `ExtractionError` on failure. The HTTP handler (endpoints module) decides how to convert this to a user-facing response (error message, fallback, etc.). **HTTP behavior is handler's responsibility, not the spec's.**

---

## What Great Looks Like

This section defines engineering standards that Phase 1 code must meet.

### Correctness Standards

1. **Coverage is binary:** If `detected_ids` contains M1, the final `FactoryConfig` contains M1, or the system raises `ExtractionError`. No partial inclusion, no degradation.
2. **Invariants hold:** Every step references a machine in `machines`; every job has ≥ 1 step; no duplicate IDs.
3. **Normalization transparency:** If `normalize_factory()` repairs a duration, we log it; if it drops a step, that step was invalid (not a coverage failure).
4. **Error propagation:** Exceptions from LLM calls, JSON parse errors, and coverage failures all become `ExtractionError` with a code and message; caller handles HTTP response.

### Determinism Standards

1. **Same input → same output:** Given identical `factory_text` and mocked LLM return, the function always produces the same `FactoryConfig` or `ExtractionError`.
2. **No randomness in logic:** Coverage assessment, ID extraction, and normalization are pure; only LLM call introduces external dependency (mocked in tests).

### LLM Prompt Isolation Standards

1. **Two calls only:** Stage 1 calls LLM once for coarse structure; Stage 2 calls LLM once for fine structure. No nested or recursive calls.
2. **Prompts are deterministic:** Same input text + same ID list → same prompt structure every time (no randomized examples, no temperature-dependent tokens).
3. **LLM calls are mockable:** Tests replace `call_llm_json()` with deterministic mock returning valid JSON; no real API calls in CI/CD.

### Testability Standards (Mock First)

1. **Unit tests mock LLM:** `extract_coarse_structure()` and `extract_steps()` are tested with mocked `call_llm_json()` returning valid JSON payloads.
2. **Integration tests mock LLM:** `OnboardingAgent.run()` tests mock all LLM calls and `normalize_factory()`.
3. **Real-LLM tests are separate:** `backend/eval/run_adversarial.py` uses real API and is never run in default `pytest` (only `pytest --use-llm`).
4. **Coverage tests are pure:** `assess_coverage()` has no mocks; it's tested with real inputs and asserted outputs.

### Code Shape Standards

1. **Pure functions:** `extract_explicit_ids()`, `assess_coverage()` have no side effects, no logging, no I/O (pure logic only).
2. **Single responsibility:** Each function does one thing: `extract_explicit_ids()` extracts IDs; `assess_coverage()` computes ratios; `OnboardingAgent.run()` orchestrates.
3. **Simple DTOs:** `PreparsedIds`, `CoarseStructure`, `RawFactoryConfig` are dumb Pydantic models with no business logic.
4. **Orchestration in one place:** All stage-to-stage wiring lives in `OnboardingAgent.run()`; no stage calls another stage.

---

## Glossary

- **PreparsedIds:** Set of machine and job IDs extracted via regex from text (stage 0)
- **CoarseStructure:** Machines and jobs with IDs and names only, no steps (stage 1 output)
- **RawFactoryConfig:** Shape-compatible with `FactoryConfig`, pre-normalization (stage 2 output)
- **FactoryConfig:** Normalized, validated configuration returned on success (stage 3 output)
- **ExtractionError:** Internal error raised by `OnboardingAgent.run()` on failure (stage 4 decision); HTTP handler converts to user response
- **Coverage Ratio:** |parsed ∩ detected| / |detected|; must be 1.0 (100%) for success
- **Hard Fail:** Raise error immediately; never degrade, never silently drop detected IDs, never return partial output
