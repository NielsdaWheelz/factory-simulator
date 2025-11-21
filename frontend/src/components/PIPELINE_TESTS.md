# Pipeline Panel Component Tests

This document outlines the test cases for the pipeline debug panel components introduced in PRF2.

## Components Tested
- **PipelineSummary**: Displays overall pipeline execution status and fallback warning
- **StageList**: Renders a list of pipeline stages with status icons and summaries

## Test Coverage

### PipelineSummary Component Tests

#### Test 1: Renders "not available" message when debug is null
**Test Case**: `test_pipeline_summary_debug_null`
- **Setup**: Pass `debug={null}` and `usedDefaultFactory={false}`
- **Expected Output**: Component renders the message "Pipeline details not available for this run."
- **Purpose**: Ensures the component gracefully handles missing debug data

#### Test 2: Renders SUCCESS status badge correctly
**Test Case**: `test_pipeline_summary_success_status`
- **Setup**: Create a `PipelineDebugPayload` with `overall_status="SUCCESS"` containing 10 stages, all with `status="SUCCESS"`
- **Expected Output**:
  - Status badge displays with green background (`status-success` class)
  - Text shows "Pipeline: all 10 stages succeeded."
- **Purpose**: Verifies correct rendering for successful pipeline execution

#### Test 3: Renders PARTIAL status badge correctly
**Test Case**: `test_pipeline_summary_partial_status`
- **Setup**: Create a `PipelineDebugPayload` with `overall_status="PARTIAL"` and `usedDefaultFactory={true}`
- **Expected Output**:
  - Status badge displays with yellow background (`status-partial` class)
  - Text shows "Pipeline: onboarding fell back to demo factory; decision pipeline succeeded."
  - Additional line shows "Using demo factory (onboarding failed)."
- **Purpose**: Verifies correct rendering for partial pipeline execution

#### Test 4: Renders FAILED status badge correctly
**Test Case**: `test_pipeline_summary_failed_status`
- **Setup**: Create a `PipelineDebugPayload` with `overall_status="FAILED"` with 3 failed stages out of 10
- **Expected Output**:
  - Status badge displays with red background (`status-failed` class)
  - Text shows "Pipeline: at least one decision stage failed (3 failed)."
- **Purpose**: Verifies correct rendering for failed pipeline execution

### StageList Component Tests

#### Test 5: Renders "no stages" message when stages array is empty
**Test Case**: `test_stage_list_empty_stages`
- **Setup**: Pass `stages={[]}` to StageList
- **Expected Output**: Component renders the message "No stages recorded for this run."
- **Purpose**: Ensures graceful handling of empty stage lists

#### Test 6: Renders all stages with correct icons and status colors
**Test Case**: `test_stage_list_renders_stages`
- **Setup**: Pass an array of 10 `PipelineStageRecord` objects:
  - 5 with `status="SUCCESS"` (green check ✓)
  - 3 with `status="FAILED"` (red X ✗)
  - 2 with `status="SKIPPED"` (grey circle ○)
- **Expected Output**:
  - 10 stage rows are rendered
  - Each row shows correct status icon with appropriate color
  - SUCCESS stages have green background
  - FAILED stages have red background
  - SKIPPED stages have grey background
- **Purpose**: Verifies correct visual representation of stage statuses

#### Test 7: Displays stage IDs correctly (O0-O4, D1-D5)
**Test Case**: `test_stage_list_stage_ids`
- **Setup**: Pass stages with IDs: O0, O1, O2, O3, O4, D1, D2, D3, D4, D5
- **Expected Output**: Each stage row displays the correct ID in the `stage-id` element
- **Purpose**: Ensures stage identification is clear

#### Test 8: Displays stage names correctly
**Test Case**: `test_stage_list_stage_names`
- **Setup**: Pass stages with various names like "Extract Explicit IDs", "Assess Coverage", "Intent Classification", etc.
- **Expected Output**: Each stage row displays the correct stage name
- **Purpose**: Ensures stage names are rendered for user identification

#### Test 9: Handles different summary types correctly
**Test Case**: `test_stage_list_summary_rendering`
- **Setup**: Pass stages with different summary types:
  - COVERAGE_ASSESSMENT: `{stage_type: "COVERAGE_ASSESSMENT", machines_coverage: 1.0, jobs_coverage: 0.8}`
  - EXPLICIT_ID_EXTRACTION: `{stage_type: "EXPLICIT_ID_EXTRACTION", explicit_machine_ids: ["M1", "M2"], explicit_job_ids: ["J1"]}`
  - INTENT_CLASSIFICATION: `{stage_type: "INTENT_CLASSIFICATION", intent_scenario_type: "RUSH_ARRIVES"}`
  - COARSE_STRUCTURE: `{stage_type: "COARSE_STRUCTURE", machines: 2, jobs: 3}`
  - JOB_STEPS_EXTRACTION: `{stage_type: "JOB_STEPS_EXTRACTION", total_steps: 6}`
- **Expected Output**:
  - COVERAGE_ASSESSMENT: "coverage: machines 100%, jobs 80%"
  - EXPLICIT_ID_EXTRACTION: "detected 2 machines, 1 jobs"
  - INTENT_CLASSIFICATION: "intent: RUSH_ARRIVES"
  - COARSE_STRUCTURE: "extracted: 2 machines, 3 jobs"
  - JOB_STEPS_EXTRACTION: "extracted 6 steps"
- **Purpose**: Verifies summary text is formatted correctly for different stage types

#### Test 10: Shows error count when stage has errors
**Test Case**: `test_stage_list_error_display`
- **Setup**: Pass a stage with `errors: ["Error 1", "Error 2", "Error 3"]`
- **Expected Output**:
  - Error indicator shows "(3 errors)" in red text
  - Title attribute contains all error messages joined by comma
- **Purpose**: Ensures errors are surfaced to the user

#### Test 11: Handles unknown summary types gracefully
**Test Case**: `test_stage_list_unknown_summary_type`
- **Setup**: Pass a stage with `summary: {unknown_field: "value"}`
- **Expected Output**: Stage displays "stage completed" as the summary text
- **Purpose**: Ensures robustness for unexpected summary structures

### Integration Tests

#### Test 12: App component wires debug state correctly
**Test Case**: `test_app_debug_state_wiring`
- **Setup**: Mock `/api/simulate` to return a `SimulateResponse` with a `debug` payload containing 5 stages
- **Expected Output**:
  - After clicking "Simulate", the pipeline panel is rendered
  - PipelineSummary component receives the debug payload
  - StageList component receives the stages array
  - All 5 stages are displayed in the list
- **Purpose**: Verifies end-to-end wiring of debug data from API response to UI

#### Test 13: App handles missing debug gracefully
**Test Case**: `test_app_missing_debug`
- **Setup**: Mock `/api/simulate` to return a `SimulateResponse` without `debug` field
- **Expected Output**:
  - PipelineSummary displays "Pipeline details not available"
  - StageList is not rendered (only rendered if `pipelineDebug` is truthy)
  - App does not crash
- **Purpose**: Ensures backward compatibility with API responses that don't include debug

#### Test 14: App resets debug on new simulation
**Test Case**: `test_app_debug_reset_on_new_simulate`
- **Setup**:
  1. Perform a simulation with debug payload (5 stages visible)
  2. Change factory description
  3. Click "Simulate" again
- **Expected Output**: pipelineDebug is temporarily reset to null, then populated with new debug data when response arrives
- **Purpose**: Ensures UI doesn't show stale debug data while loading

## Implementation Notes

These tests should be implemented using:
- **Framework**: React Testing Library + Vitest (to be added to frontend dependencies)
- **Location**: `frontend/src/components/__tests__/`
- **File Structure**:
  - `frontend/src/components/__tests__/PipelineSummary.test.tsx` (Tests 1-4)
  - `frontend/src/components/__tests__/StageList.test.tsx` (Tests 5-11)
  - `frontend/src/__tests__/App.integration.test.tsx` (Tests 12-14)

## Coverage Goals

- **PipelineSummary**: 100% line coverage
- **StageList**: 100% line coverage, all summary type handling
- **App Integration**: Key user paths covered

## Manual Testing Checklist

For manual verification until automated tests are in place:

- [ ] Load the app and simulate with debug payload - verify pipeline panel appears
- [ ] Verify status badges show correct colors for SUCCESS (green), PARTIAL (yellow), FAILED (red)
- [ ] Verify all stage rows show with correct status icons
- [ ] Verify stage names and summaries are readable
- [ ] Simulate without debug payload - verify "not available" message instead of crashing
- [ ] Run multiple simulations - verify debug data updates correctly
- [ ] Check responsive layout - verify stage rows don't wrap oddly on narrow screens
