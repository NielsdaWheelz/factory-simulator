# PR5 Implementation Summary: "The Essentials"

**Objective:** Harden behavior and visibility in the onboarding pipeline without changing HTTP contracts or core models.

**Status:** ✅ Complete

---

## Overview

PR5 hardened the factory-simulator's onboarding pipeline by:

1. **Backend:** Adding negative integration tests to lock behavior around coverage enforcement, error handling, and fallback logic
2. **Frontend:** Adding visible banners to alert users when the system fell back to a demo factory
3. **Tooling:** Creating a manual sanity harness for quick end-to-end LLM verification

All changes maintain backward compatibility with existing HTTP contracts and Pydantic models.

---

## BLOCK 1: Backend Negative Integration Tests

### Files Modified
- `backend/tests/test_onboarding_agent_orchestration.py`: Added `TestOnboardingAgentNegativeIntegration` class
- `backend/tests/test_orchestrator.py`: Added `TestRunOnboardingNegativeIntegration` class
- `backend/tests/test_server_simulate.py`: Added `TestSimulateEndpointMetaPropagation` class

### Tests Added

#### OnboardingAgent orchestration (4 new tests)
Verify that `OnboardingAgent.run()` correctly enforces 100% ID coverage and handles all error cases:

1. **test_onboarding_agent_raises_on_coverage_mismatch**
   - Tests that agent raises `ExtractionError` with code `COVERAGE_MISMATCH` when coverage < 100%
   - Verifies error contains missing IDs and coverage ratios in details dict

2. **test_onboarding_agent_raises_on_normalization_failure**
   - Tests that agent re-raises `ExtractionError` from `validate_and_normalize` without transformation
   - Ensures `NORMALIZATION_FAILED` errors propagate exactly as raised

3. **test_onboarding_agent_wraps_raw_llm_error_as_llm_failure**
   - Tests that non-`ExtractionError` exceptions from LLM calls are wrapped as `LLM_FAILURE`
   - Verifies original exception type and message are captured in error details

4. **test_onboarding_agent_wraps_raw_validation_error_as_llm_failure**
   - Tests that `ValueError` from `extract_steps` is wrapped as `LLM_FAILURE`
   - Ensures stage name is captured in error details

#### run_onboarding fallback behavior (5 new tests)
Verify that `run_onboarding()` reliably catches agent errors and falls back to toy factory:

1. **test_run_onboarding_falls_back_on_coverage_mismatch_extraction_error**
   - Tests fallback is triggered on `COVERAGE_MISMATCH` error
   - Verifies meta shows `used_default_factory=True` and error is documented

2. **test_run_onboarding_falls_back_on_normalization_failure**
   - Tests fallback on `NORMALIZATION_FAILED` error
   - Verifies error details are captured in `onboarding_errors` list

3. **test_run_onboarding_falls_back_on_llm_failure**
   - Tests fallback on `LLM_FAILURE` error
   - Ensures LLM errors don't propagate to caller

4. **test_run_onboarding_success_passthrough**
   - Tests successful path returns agent output directly
   - Verifies meta shows `used_default_factory=False` with no errors

5. **test_run_onboarding_meta_has_required_fields**
   - Tests that `OnboardingMeta` always has required fields:
     - `used_default_factory: bool`
     - `onboarding_errors: list[str]`
     - `inferred_assumptions: list[str]`

#### Simulate endpoint meta propagation (3 new tests)
Verify that `/api/simulate` correctly propagates onboarding metadata:

1. **test_simulate_endpoint_propagates_used_default_factory_flag**
   - Tests that `used_default_factory=True` flag reaches frontend
   - Frontend can display fallback warning based on this flag

2. **test_simulate_endpoint_propagates_onboarding_errors**
   - Tests that `onboarding_errors` list is included in response
   - Frontend can display error messages to user

3. **test_simulate_endpoint_meta_on_success**
   - Tests that successful onboarding shows `used_default_factory=False`
   - Verifies `onboarding_errors` is empty on success

### Test Results
✅ All 405 backend tests pass (including 12 new PR5 tests)

---

## BLOCK 2: Frontend UI Banners

### Files Modified
- `frontend/src/App.tsx`: Added fallback warning banners in factory and scenarios panels
- `frontend/src/App.css`: Added styling for fallback-related UI elements

### UI Components Added

#### Fallback Warning Banner (Factory Panel)
Located at top of factory configuration panel when `meta.used_default_factory === true`:

- **Title:** "⚠️ Using Demo Factory"
- **Message:** Clear explanation that parsing failed and a demo factory is being used
- **Errors Section:** Lists `onboarding_errors` items (if any) to help user understand what went wrong

**CSS Classes:** `.fallback-banner`, `.banner-header`, `.banner-message`, `.errors-box`, `.errors-list`

**Color Scheme:**
- Background: Amber/yellow (`#fff3cd`) for warning status
- Border: 2px solid amber (`#ffc107`)
- Text: Dark amber (`#856404`)

#### Fallback Notice (Scenarios Panel)
Located at top of scenarios & metrics panel when fallback occurred:

- **Message:** Brief note that scenarios are based on demo factory, not user input
- **Purpose:** Prevents user confusion about what they're seeing

**CSS Classes:** `.fallback-notice`

**Color Scheme:**
- Background: Light blue (`#e7f3ff`) for informational note
- Border: 1px solid blue (`#b3d9ff`)
- Text: Dark blue (`#004085`)

### User Experience
- Banners are visible without scrolling (positioned at top of panels)
- High-contrast colors make them noticeable
- Clear language explains what happened and why
- No changes to factory data display itself (just visual feedback about its source)

### Type Safety
- No changes to `api.ts` TypeScript interfaces
- All `meta` fields were already available in `OnboardingMeta` type
- App compiles with zero TypeScript errors

---

## BLOCK 3: Real-LLM Sanity Harness

### File Created
- `backend/eval/run_onboard_sanity.py`: Manual-only sanity harness for quick LLM verification

### Purpose
Provides a lightweight script to quickly verify onboarding behavior with real LLM calls on canonical test cases.

**Not for pytest** - designed for manual eyeballing of behavior, not automated assertions.

### Test Cases Included

1. **Canonical Good** (`canonical_good`)
   - Clean 3-machine, 3-job factory description
   - Expected: Parses cleanly with 100% coverage

2. **Messy SOP** (`messy_sop`)
   - SOP-like text with chatter but still parseable
   - Expected: Parses despite messiness, possible minor coverage loss

3. **Broken Minimal** (`broken_minimal`)
   - Intentionally vague/unparseable text
   - Expected: Falls back to toy factory with clear error message

### Output Format
For each case, prints:
- Case ID and name
- Stage 0 explicit ID detection (machines/jobs found via regex)
- Stage 1-4 final factory structure
- Coverage assessment (% of detected IDs that made it through)
- Whether fallback was triggered
- Any onboarding error messages

No assertions, no JSON output - just eyeball-friendly summaries.

### Usage
```bash
# Run all test cases with real LLM (will take ~1 minute)
python -m backend.eval.run_onboard_sanity

# Output goes to stdout - review for expected patterns
```

---

## Testing & Verification

### Backend Test Suite
✅ **All 405 tests pass** (90 seconds)

Breakdown:
- 12 new PR5 tests
- 393 existing tests (all still passing)
- Zero failures, zero skips

Run with:
```bash
python -m pytest backend/tests/ -v
```

### Frontend Build & Type Check
✅ **TypeScript:** 0 errors, 0 warnings
✅ **Build:** Successful (148 KB JS bundle, 4.38 KB CSS)

Run with:
```bash
cd frontend && npm run build
```

### Sanity Harness (Manual)
Can be run manually to verify real-LLM behavior:
```bash
python -m backend.eval.run_onboard_sanity
```

---

## Contract Compliance

### ✅ No Breaking Changes
All existing HTTP contracts preserved:

- `POST /api/onboard`
  - Request shape: unchanged
  - Response shape: unchanged (still has `factory` + `meta`)

- `POST /api/simulate`
  - Request shape: unchanged
  - Response shape: unchanged (still has `meta` with `used_default_factory` and `onboarding_errors`)

- Pydantic models: All fields preserved
  - `FactoryConfig`: Unchanged
  - `Machine`, `Job`, `Step`: Unchanged
  - `OnboardingMeta`: Unchanged (already had all fields)
  - `OnboardingResponse`, `SimulateResponse`: Unchanged

### ✅ Backward Compatible
- Frontend only reads existing `meta` fields that were already in API contracts
- Backend tests only verify existing behavior (negative cases that were always required)
- No new dependencies introduced

---

## Summary of Changes

| Component | Change | Impact |
|-----------|--------|--------|
| Backend Tests | +12 new tests | Locks behavior around coverage enforcement, error handling, fallback |
| Frontend UI | +2 banner components | Visible warning when fallback occurs |
| Frontend CSS | +~60 lines | Styling for fallback banners |
| Eval Harness | +1 new module | Manual sanity checking with real LLM |
| HTTP Contracts | None | Fully backward compatible |
| Core Models | None | No changes needed |

---

## Key Guarantees Established by Tests

1. **Coverage Enforcement**
   - OnboardingAgent raises on coverage < 100%
   - Never returns partial/degraded configs

2. **Error Handling**
   - All extraction errors are properly typed and propagated
   - LLM failures are wrapped and documented
   - Normalization failures trigger hard stops (not partial output)

3. **Fallback Behavior**
   - run_onboarding catches all agent errors
   - Always falls back to toy factory on error
   - Errors are documented in meta for frontend visibility

4. **Meta Propagation**
   - Onboarding meta flows through to /api/simulate response
   - Frontend can read used_default_factory flag
   - Frontend can display onboarding_errors to user

5. **Frontend Honesty**
   - Banners clearly indicate when system fell back to demo
   - Errors explain what went wrong (when available)
   - No false impression of successful custom factory parsing

---

## Next Steps (Not in PR5)

Possible enhancements for future PRs:

1. **Enhanced Error Messages:** More detailed explanations in onboarding_errors
2. **Retry UI:** Allow user to modify input and retry parsing
3. **Logging:** Structured logging of onboarding decisions in production
4. **Metrics:** Track failure rates by error type
5. **Prompt Tuning:** Improve LLM extraction reliability to reduce fallback frequency

---

## How to Review

1. **Run tests:** `python -m pytest backend/tests/ -v`
2. **Build frontend:** `cd frontend && npm run build`
3. **Review banners:** Check `frontend/src/App.tsx` lines 101-165
4. **Review styles:** Check `frontend/src/App.css` lines 116-173
5. **Sanity check (optional):** `python -m backend.eval.run_onboard_sanity` with real LLM

All changes maintain the principle: **make failures visible, not silent.**
