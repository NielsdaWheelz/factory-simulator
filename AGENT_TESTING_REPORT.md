# Agent Testing Coverage Report

**Date**: November 20, 2025
**Branch**: llm-tests
**Purpose**: Survey existing agent harness tests and identify gaps for input→output modeling tests

---

## Executive Summary

The factory-simulator project has **4 LLM-backed agents** orchestrating the factory description parsing → decision-making → briefing pipeline. Currently, the test suite has:

- ✅ **Unit tests with mocked LLM** (test_agents_llm.py) - Testing agent behavior with mocked responses
- ✅ **Integration tests** (test_run_onboarded_pipeline.py, test_orchestrator.py) - Testing agent coordination
- ✅ **Adversarial evaluation harness** (backend/eval/) - Comprehensive test corpus for edge cases
- ❌ **Limited input→output modeling tests** - Missing systematic validation that human inputs produce expected LLM outputs

**Gap**: The existing tests verify that agents *handle* LLM responses correctly, but do not verify that agents *produce correct outputs* given specific human inputs. This report outlines what needs to be added for comprehensive input-output validation.

---

## 1. Agent Architecture

### 1.1 The Four Agents

| Agent | Location | Input | Output | LLM Used |
|-------|----------|-------|--------|----------|
| **OnboardingAgent** | agents.py:41-538 | `factory_text` (string) | `FactoryConfig` (machines, jobs, steps) | Yes (call_llm_json) |
| **IntentAgent** | agents.py:592-718 | `user_text`, optional factory context | `ScenarioSpec` + explanation string | Yes |
| **FuturesAgent** | agents.py:721-835 | `ScenarioSpec`, optional factory context | `list[ScenarioSpec]` (1-3) + justification string | Yes |
| **BriefingAgent** | agents.py:838-963 | `ScenarioMetrics`, optional context strings | Markdown briefing string | Yes |

### 1.2 Pipeline Flow (Orchestrator)

```
factory_text
  ↓
OnboardingAgent.run()
  ↓
FactoryConfig (machines, jobs, steps)
  ↓
situation_text → IntentAgent.run(situation_text, factory)
  ↓
ScenarioSpec + explanation_context
  ↓
FuturesAgent.run(scenario, factory)
  ↓
list[ScenarioSpec] + futures_context
  ↓
For each ScenarioSpec: simulate() → metrics
  ↓
Primary metrics + contexts → BriefingAgent.run()
  ↓
Markdown briefing (with feasibility assessment)
```

---

## 2. Current Test Coverage

### 2.1 Test File: test_agents_llm.py (32 KB)

**Purpose**: Unit tests for agents with mocked `call_llm_json`

**Test Classes & Coverage**:

| Class | Test Count | Scope |
|-------|-----------|-------|
| `TestOnboardingAgentWithMockedLLM` | 10 tests | ✅ Full coverage of fallback, error handling, edge cases |
| `TestNormalizeScenarioSpec` | 7 tests | ✅ Scenario spec normalization/validation |
| `TestIntentAgentWithMockedLLM` | 7 tests | ✅ Intent extraction, BASELINE/RUSH_ARRIVES/M2_SLOWDOWN, fallback |
| `TestFuturesAgentWithMockedLLM` | 5 tests | ⚠️ Basic scenario generation, truncation, fallback |
| `TestBriefingAgentWithMockedLLM` | 5 tests | ⚠️ Markdown generation, context handling, fallback |
| `TestAgentDeterminism` | 3 tests | ✅ Deterministic output validation |

**Key Tests**:
- OnboardingAgent: LLM call signature, fallback on errors, empty input handling, minimal/large factories
- IntentAgent: Correct scenario type extraction, fallback to BASELINE, invalid job ID normalization
- FuturesAgent: Single and multiple scenario generation, truncation to 3 scenarios, fallback
- BriefingAgent: Markdown output, context parameter passing, fallback

**What's Missing**:
- ❌ **Input-output modeling**: No tests that verify "if human describes X factory structure, agent produces Y FactoryConfig"
- ❌ **Semantic validation**: Tests don't check that parsed machines/jobs match the input intent
- ❌ **Scenario coherence**: No tests ensuring generated scenarios respect factory constraints
- ❌ **Briefing accuracy**: No tests validating that briefing reflects actual metrics and constraints

### 2.2 Test File: test_run_onboarded_pipeline.py (25 KB)

**Purpose**: Integration tests for the full agent pipeline

**Key Test Classes**:
- `TestOnboardingAgentIntegration` - End-to-end onboarding tests
- `TestAgentChaining` - Multi-agent pipeline coordination
- Failure ladder tests (OK/DEGRADED/FALLBACK modes)

**Scope**:
- ✅ Agent chaining and data flow
- ✅ Fallback mechanisms across pipeline
- ✅ Error handling and degradation

**What's Missing**:
- ❌ **End-to-end input validation**: No tests like "given clean_canonical factory description, verify FactoryConfig matches expected structure"
- ❌ **Scenario validation**: No tests ensuring IntentAgent → FuturesAgent → simulation produces coherent results
- ❌ **Briefing correctness**: No tests validating briefing content matches simulation results

### 2.3 Test File: test_orchestrator.py (37 KB)

**Purpose**: Testing orchestrator functions and pipeline structure

**Key Test Classes**:
- `TestRunPipelineStructure` - Pipeline structure validation
- Tests for `run_pipeline`, `run_onboarding`, `run_decision_pipeline`, `run_onboarded_pipeline`

**Scope**:
- ✅ Function signatures and return types
- ✅ Pipeline data flow
- ✅ Error propagation

**What's Missing**:
- ❌ **Semantics**: Pipeline tests don't validate output correctness relative to inputs

### 2.4 Adversarial Evaluation Harness (backend/eval/)

**Purpose**: Stress-test pipeline with messy, edge-case inputs

**Components**:
- `run_adversarial.py` - CLI harness (opt-in, not part of normal pytest)
- `adversarial_cases.yaml` - 12 curated test cases
- `invariants.py` - Structural validation helpers

**Test Cases** (12 total):
1. `clean_canonical` - Well-formatted factory, clear constraints
2. `messy_sop` - Noisy prose-style description
3. `contradictory_info` - Conflicting machine/job definitions
4. `missing_machines` - References to decommissioned equipment
5. `large_factory` - Stress test: 8 machines, 20 jobs
6. `invalid_durations` - Negative, zero, fractional durations
7. `circular_routing` - Jobs revisit machines (non-linear flow)
8. `empty_factory` - Trivial/empty input
9. `impossible_constraints` - Infeasible scheduling scenario
10. `noisy_realistic` - Realistic noise in factory description
11. `numeric_due_times` - Pure numeric time formats
12. `short_durations` - All 1-hour jobs (minimal processing)

**Current Validation** (invariants.py):
- ✅ Factory invariants (valid machine refs, duration bounds, structural limits)
- ✅ Metrics invariants (metric bounds, job lateness validity)
- ✅ HTTP endpoint testing (optional --http flag)
- ⚠️ JSON report generation for manual inspection

**What's Missing**:
- ❌ **Expected output assertions**: No specification of what FactoryConfig *should* be produced for each case
- ❌ **Semantic checks**: Invariants check structural bounds but not whether parsed machines/jobs match input intent
- ❌ **Scenario validation**: No checks that IntentAgent/FuturesAgent produce sensible outputs for each case
- ❌ **Automated comparison**: Reports are generated for manual inspection, not automatically validated

---

## 3. What Exists: Detailed Breakdown

### 3.1 OnboardingAgent Tests ✅ (Partially Complete)

**What's Tested**:
- ✅ Returns FactoryConfig from mocked LLM
- ✅ Calls LLM with correct signature (prompt, schema)
- ✅ Fallback to toy factory on errors (RuntimeError, ValueError, TimeoutError, KeyError, generic Exception)
- ✅ Empty input handling
- ✅ Minimal factory (1 machine, 1 job)
- ✅ Large factory (5 machines, 7 jobs)
- ✅ Never raises exceptions

**What's NOT Tested** ❌:
- **Semantic correctness of parsing**: No tests verify that parsed machines/jobs *match* the factory_description
  - Example: "Assembly (M1), Drill (M2), Packing (M3). J1: M1→2h, M2→3h, M3→1h, due 10am"
  - Should verify: FactoryConfig has exactly 3 machines with those roles, J1 has 3 steps with correct durations
- **Complex routing**: No tests for multi-step jobs with varied durations
- **Edge case semantics**: No tests for time interpretation (10am vs "10", "noon", "end of day")
- **Fallback quality**: No tests verify fallback output is reasonable or matches input when possible
- **Failure recovery**: No tests for partial parsing success scenarios

### 3.2 IntentAgent Tests ✅ (Partial)

**What's Tested**:
- ✅ Extracts BASELINE, RUSH_ARRIVES, M2_SLOWDOWN scenarios
- ✅ Fallback to BASELINE on LLM error
- ✅ Invalid job ID normalization (downgrades to BASELINE)
- ✅ Returns (ScenarioSpec, explanation_string) tuple

**What's NOT Tested** ❌:
- **Scenario type correctness**: No tests verify IntentAgent *correctly* interprets user intent
  - Example: "J2 just arrived and must be done first" → should produce RUSH_ARRIVES with rush_job_id="J2"
  - Current test only checks *that* it handles these scenarios, not that it *identifies* them correctly
- **Explanation quality**: No validation of explanation_string coherence
- **Multi-scenario hints**: No tests for user inputs that could map to multiple scenario types
- **Constraint preservation**: No tests verify situation_text constraints are captured in the explanation

### 3.3 FuturesAgent Tests ⚠️ (Minimal)

**What's Tested**:
- ✅ Generates 1-3 scenario variations
- ✅ Truncates to max 3 if LLM returns more
- ✅ Fallback to [original_spec] on LLM error

**What's NOT Tested** ❌:
- **Scenario diversity**: No tests verify generated scenarios are actually different/meaningful
- **Scenario coherence**: No tests check scenarios respect factory constraints (valid job IDs, machine availability)
- **Justification quality**: No validation that justification_string explains why scenarios were chosen
- **Scenario ranking**: No tests for scenario prioritization or ordering
- **Fallback diversity**: When LLM fails, should still offer alternatives (currently just [original_spec])

### 3.4 BriefingAgent Tests ⚠️ (Minimal)

**What's Tested**:
- ✅ Returns markdown string
- ✅ Accepts optional context parameters (intent_context, futures_context)
- ✅ Fallback to deterministic template on LLM error

**What's NOT Tested** ❌:
- **Briefing accuracy**: No tests verify briefing reflects actual metrics (makespan, lateness, bottleneck)
- **Feasibility assessment**: No tests validate constraint violation detection
- **Conflict detection**: No tests for infeasible scenario flags
- **Context integration**: No tests verify context strings are properly incorporated
- **Markdown quality**: No tests for valid markdown output, table formatting, readability
- **Metric coverage**: No tests ensure all relevant metrics are included in briefing

---

## 4. What Remains to Be Done

### 4.1 OnboardingAgent Input→Output Tests

**Goal**: Verify that when a human describes a factory with X machines, Y jobs, etc., the agent produces a FactoryConfig matching expected structure.

**Test Cases to Add** (examples):

```python
class TestOnboardingAgentSemanticCorrectness:
    """Verify OnboardingAgent correctly parses factory descriptions into matching FactoryConfig."""

    # Case 1: Clean canonical → verify exact machine/job structure
    def test_parses_clean_canonical_correctly(self):
        """Given clean_canonical description, verify FactoryConfig matches:
        - 3 machines (M1, M2, M3)
        - 3 jobs (J1, J2, J3)
        - J1: 3 steps (M1→2h, M2→3h, M3→1h), due 10am
        - J2: 3 steps (M1→1h, M2→4h, M3→2h), due 12pm
        - J3: 2 steps (M1→1h, M2→2h), due 9am
        """

    # Case 2: Messy prose → verify parser recovers intent despite noise
    def test_recovers_structure_from_messy_prose(self):
        """Given messy_sop description, verify parsed machines/jobs match original intent
        despite prose formatting, abbreviations, and noisy context."""

    # Case 3: Contradictory → verify parser picks consistent interpretation
    def test_handles_contradictions_consistently(self):
        """Given contradictory_info case, verify parser produces *one* coherent FactoryConfig
        (even if it picks first mention, or flags ambiguity in logs)."""

    # Case 4: Missing machines → verify error recovery
    def test_handles_missing_machine_refs(self):
        """Given missing_machines case, verify parser either:
        a) Skips steps referencing unavailable machines, or
        b) Flags with warning and falls back"""

    # Case 5: Invalid durations → verify normalization
    def test_normalizes_invalid_durations(self):
        """Given invalid_durations case (negative, zero, fractional hours),
        verify parser either normalizes to valid bounds or skips steps."""

    # Case 6: Time interpretation → verify due_time parsing
    def test_interprets_time_formats_correctly(self):
        """Verify parser handles:
        - "10am" → 10, "noon" → 12, "9" → 9
        - "10:00" → 10, "by 10" → 10
        - Relative times if mentioned"""
```

**Success Criteria**:
- For each adversarial case, specify the *expected* FactoryConfig (machine count, job count, step structure, due times)
- Compare agent output against expected values
- Report deviations as test failures or warnings

**Effort**: 2-3 days to define expected outputs and write ~15-20 test cases

---

### 4.2 IntentAgent Scenario Identification Tests

**Goal**: Verify IntentAgent correctly maps situation_text → ScenarioSpec.

**Test Cases to Add**:

```python
class TestIntentAgentSemanticCorrectness:
    """Verify IntentAgent correctly identifies scenario intent from situation_text."""

    def test_identifies_rush_arrives_intent(self):
        """Given 'J2 just arrived, must be done first', verify IntentAgent outputs:
        - scenario_type = RUSH_ARRIVES
        - rush_job_id = "J2"
        - explanation mentions urgency/priority"""

    def test_identifies_m2_slowdown_intent(self):
        """Given 'M2 is broken, will run at 50% speed', verify:
        - scenario_type = M2_SLOWDOWN
        - slowdown_factor ≈ 0.5 (or 2.0 for "twice as slow")"""

    def test_identifies_baseline_for_normal_operations(self):
        """Given 'normal day, standard operations', verify:
        - scenario_type = BASELINE
        - no rush_job_id or slowdown_factor"""

    def test_captures_constraint_in_explanation(self):
        """Given situation with explicit constraints, verify explanation captures them."""

    def test_handles_ambiguous_intent(self):
        """Given ambiguous situation text, verify IntentAgent:
        - Picks most likely scenario, or
        - Falls back to BASELINE with explanation of ambiguity"""
```

**Success Criteria**:
- For each adversarial case's situation_text, specify expected ScenarioSpec
- Validate scenario_type identification
- Validate rush_job_id / slowdown_factor extraction
- Validate explanation coherence

**Effort**: 1-2 days to define expected scenarios and write ~10 test cases

---

### 4.3 FuturesAgent Scenario Diversity Tests

**Goal**: Verify FuturesAgent generates meaningful, diverse scenario alternatives.

**Test Cases to Add**:

```python
class TestFuturesAgentSemanticCorrectness:
    """Verify FuturesAgent generates coherent, diverse scenario alternatives."""

    def test_generates_alternative_scenarios(self):
        """Given a base BASELINE scenario, verify FuturesAgent returns 2-3 distinct alternatives:
        - Each respects factory constraints (valid job IDs, machine availability)
        - Each is semantically different (e.g., different job ordering priority)
        - Justification explains reasoning for each alternative"""

    def test_respects_factory_constraints(self):
        """Verify all generated scenarios reference only valid job IDs and machines."""

    def test_scenarios_have_justification(self):
        """Verify each generated scenario is explained in the justification string."""

    def test_handles_infeasible_base_scenario(self):
        """Given impossible_constraints scenario, verify FuturesAgent:
        - Acknowledges infeasibility in generated scenarios
        - Suggests pragmatic alternatives (reduce scope, extend deadline, etc.)"""
```

**Success Criteria**:
- Scenarios are structurally valid (all job/machine IDs exist)
- Scenarios are semantically diverse (not all identical)
- Justification text explains diversity
- Fallback (single [base] scenario) is reasonable when no alternatives exist

**Effort**: 1 day to write ~8 test cases

---

### 4.4 BriefingAgent Briefing Accuracy Tests

**Goal**: Verify BriefingAgent produces briefings that accurately reflect metrics and constraints.

**Test Cases to Add**:

```python
class TestBriefingAgentSemanticCorrectness:
    """Verify BriefingAgent accurately summarizes metrics and feasibility."""

    def test_briefing_mentions_makespan(self):
        """Given ScenarioMetrics with makespan=10 hours, verify briefing mentions completion time."""

    def test_briefing_identifies_bottleneck_machine(self):
        """Given metrics with bottleneck_machine_id='M2', verify briefing flags M2 as constraint."""

    def test_briefing_assesses_feasibility(self):
        """Given metrics where some jobs are late:
        - Verify briefing flags infeasible scenario
        - Mentions which jobs miss deadlines
        - Suggests severity of lateness"""

    def test_briefing_integrates_context_strings(self):
        """Given intent_context and futures_context, verify briefing incorporates them:
        - References the original user intent
        - Explains scenario choice"""

    def test_briefing_covers_all_metrics(self):
        """Verify briefing mentions:
        - Total makespan
        - Bottleneck machine and utilization
        - Job lateness (any late jobs)
        - Feasibility assessment"""

    def test_briefing_markdown_validity(self):
        """Verify briefing output is valid markdown (proper headers, formatting)."""
```

**Success Criteria**:
- Briefing content matches metrics (makespan, bottleneck, lateness values)
- Feasibility flags are correct
- Context strings are incorporated
- Markdown is properly formatted

**Effort**: 2 days to write ~12 test cases and define expected briefing patterns

---

### 4.5 End-to-End Pipeline Integration Tests

**Goal**: Verify entire pipeline (OnboardingAgent → IntentAgent → FuturesAgent → BriefingAgent) produces coherent results.

**Test Cases to Add**:

```python
class TestFullPipelineIntegration:
    """Verify entire agent pipeline produces coherent end-to-end results."""

    def test_clean_canonical_full_pipeline(self):
        """Run full pipeline on clean_canonical case, verify:
        - FactoryConfig matches expected structure
        - IntentAgent correctly interprets situation
        - FuturesAgent generates sensible alternatives
        - BriefingAgent summarizes coherently"""

    def test_messy_sop_full_pipeline(self):
        """Run full pipeline on messy_sop, verify pipeline recovers intent despite noise."""

    def test_impossible_constraints_full_pipeline(self):
        """Run full pipeline on impossible_constraints, verify:
        - All agents complete without error
        - BriefingAgent correctly flags infeasibility
        - Degradation happens gracefully"""

    def test_pipeline_handles_missing_machines(self):
        """Given missing_machines case, verify pipeline:
        - Normalizes factory (skips or flags invalid refs)
        - Continues through decision pipeline
        - Briefing reflects degradation"""
```

**Success Criteria**:
- No unhandled exceptions
- Agents coordinate correctly (output of one matches input of next)
- Final briefing is coherent and useful
- Degradation is graceful and explicit

**Effort**: 1 day to write ~5 comprehensive end-to-end tests

---

### 4.6 Adversarial Harness Enhancements

**Current State**:
- Generates JSON reports with intermediate agent outputs
- Validates structural invariants only
- Reports available for manual inspection

**Needed Enhancements**:

```python
# adversarial_cases.yaml: Add expected outputs for each case

cases:
  - id: clean_canonical
    kind: simulate
    factory_description: |
      ...
    situation_text: |
      ...

    # NEW: Expected outputs
    expected_factory:
      machines: [
        {id: "M1", name: "Assembly workstation"},
        {id: "M2", name: "Drill and mill station"},
        {id: "M3", name: "Packaging station"},
      ]
      jobs: [
        {id: "J1", steps: 3, due_time_hour: 10},
        {id: "J2", steps: 3, due_time_hour: 12},
        {id: "J3", steps: 2, due_time_hour: 9},
      ]

    expected_scenario:
      scenario_type: "BASELINE"
      # (no rush_job_id or slowdown)

    expected_feasibility: "OK"  # or DEGRADED / INFEASIBLE
    tags: ["clean", "canonical", "baseline"]
```

```python
# invariants.py: Add semantic validation functions

def validate_factory_structure(actual_factory: FactoryConfig, expected: dict) -> list[str]:
    """Check that parsed factory matches expected machine/job structure.
    Returns list of violations (empty if all pass)."""

def validate_scenario_intent(scenario_spec: ScenarioSpec, situation_text: str) -> list[str]:
    """Check that scenario type matches situation intent."""

def validate_briefing_accuracy(briefing: str, metrics: ScenarioMetrics) -> list[str]:
    """Check that briefing mentions expected metrics and constraints."""
```

```python
# run_adversarial.py: Add semantic validation

for case in cases:
    report = run_case(case)

    # Structural invariants (existing)
    invariants = check_invariants(report)

    # NEW: Semantic validation
    if case.expected_factory:
        factory_violations = validate_factory_structure(
            report['onboarding']['factory'],
            case.expected_factory
        )
        report['invariants']['factory_semantic_violations'] = factory_violations

    if case.expected_scenario:
        scenario_violations = validate_scenario_intent(
            report['agents']['intent_scenario'],
            case.situation_text
        )
        report['invariants']['scenario_semantic_violations'] = scenario_violations

    # Report pass/fail
    if factory_violations or scenario_violations:
        print(f"[{case.id}] SEMANTIC VIOLATIONS DETECTED")
    else:
        print(f"[{case.id}] SEMANTIC VALIDATION PASSED")
```

**Success Criteria**:
- Each adversarial case has documented expected factory structure
- Each case has expected scenario type / parameters
- Harness validates semantic correctness, not just structural validity
- Reports flag semantic violations clearly

**Effort**: 2-3 days to add expected outputs to all 12 cases and write validation logic

---

## 5. Implementation Roadmap

### Phase 1: OnboardingAgent Modeling (Highest Priority)
- **Duration**: 2-3 days
- **Goal**: Establish input→output mapping for factory descriptions
- **Deliverables**:
  - Define expected FactoryConfig for each adversarial case
  - Write 15-20 semantic correctness tests
  - Add expected_factory to adversarial_cases.yaml
- **Impact**: Catches parsing regressions early, validates LLM prompt quality

### Phase 2: IntentAgent & FuturesAgent Scenario Modeling
- **Duration**: 2-3 days
- **Goal**: Verify scenario identification and generation
- **Deliverables**:
  - Define expected scenario type for each case
  - Write 10 intent identification tests
  - Write 8 futures generation tests
  - Add expected_scenario to adversarial_cases.yaml
- **Impact**: Ensures decision pipeline receives valid scenario specs

### Phase 3: BriefingAgent Accuracy Testing
- **Duration**: 2 days
- **Goal**: Validate briefing reflects metrics and constraints
- **Deliverables**:
  - Write 12 briefing accuracy tests
  - Define briefing pattern specs
  - Add validation to harness
- **Impact**: Ensures user-facing output is accurate

### Phase 4: End-to-End Pipeline Integration
- **Duration**: 1 day
- **Goal**: Verify full pipeline coherence
- **Deliverables**:
  - Write 5 comprehensive end-to-end tests
  - Test all 12 adversarial cases through full pipeline
  - Verify degradation/fallback behavior
- **Impact**: Catches integration bugs between agents

### Phase 5: Adversarial Harness Enhancement
- **Duration**: 2-3 days
- **Goal**: Automate semantic validation in harness
- **Deliverables**:
  - Add expected_factory, expected_scenario to all cases
  - Implement semantic validation functions
  - Update run_adversarial.py to check semantic correctness
  - Update reports to include semantic violation flags
- **Impact**: Continuous validation on LLM changes, regression detection

---

## 6. Testing Strategy Summary

### Unit Tests (test_agents_llm.py)
- **Existing**: Test agent behavior with mocked LLM responses
- **Needed**: Add input→output semantic correctness tests for each agent
- **Pattern**: Mock LLM with realistic response, verify output matches expected structure

### Integration Tests (test_run_onboarded_pipeline.py)
- **Existing**: Test agent coordination and fallback behavior
- **Needed**: Add end-to-end case tests using adversarial corpus
- **Pattern**: Run full pipeline on specific cases, verify coherence

### Adversarial Harness (backend/eval/)
- **Existing**: Structural invariant validation, JSON reports
- **Needed**: Semantic validation, expected output specifications, automated assertions
- **Pattern**: Define expected outputs, automate comparison in harness

---

## 7. Estimated Effort Summary

| Phase | Task | Duration | Priority |
|-------|------|----------|----------|
| 1 | OnboardingAgent I/O tests + expected outputs | 2-3 days | 🔴 High |
| 2 | IntentAgent + FuturesAgent scenario tests | 2-3 days | 🔴 High |
| 3 | BriefingAgent accuracy tests | 2 days | 🟡 Medium |
| 4 | End-to-end pipeline tests | 1 day | 🟡 Medium |
| 5 | Harness enhancement + automation | 2-3 days | 🟢 Lower |
| **Total** | | **10-15 days** | |

---

## 8. Success Metrics

After implementation, the test suite should:

1. ✅ Validate that all agents produce structurally correct outputs
2. ✅ Validate that agent outputs are semantically correct (match input intent)
3. ✅ Validate that agents coordinate correctly (output of one = valid input to next)
4. ✅ Validate that end-to-end pipeline produces coherent results
5. ✅ Catch regressions when LLM prompts change
6. ✅ Catch integration bugs between agents
7. ✅ Provide clear error messages when validation fails

---

## Appendix: Current Test Inventory

### Full Test List

**test_agents_llm.py** (32 tests total):
- TestOnboardingAgentWithMockedLLM: 10
- TestNormalizeScenarioSpec: 7
- TestIntentAgentWithMockedLLM: 7
- TestFuturesAgentWithMockedLLM: 5
- TestBriefingAgentWithMockedLLM: 5
- TestAgentDeterminism: 3

**test_run_onboarded_pipeline.py**: Integration tests (exact count varies)

**test_orchestrator.py**: Orchestration tests (exact count varies)

**backend/eval/**: Adversarial harness with 12 curated cases (not part of normal pytest)

### Files Modified for This Analysis
- backend/agents.py (4 agents)
- backend/models.py (data models)
- backend/tests/test_agents_llm.py (existing tests)
- backend/tests/test_run_onboarded_pipeline.py (integration tests)
- backend/eval/adversarial_cases.yaml (12 test cases)

---

**End of Report**
