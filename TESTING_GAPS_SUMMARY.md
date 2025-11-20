# Agent Testing Gaps - Quick Summary

## The Four Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENT PIPELINE                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  factory_text                                                   │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────────────────────────┐                              │
│  │  OnboardingAgent             │  ✅ Tested fallback          │
│  │  factory_text → FactoryConfig│  ❌ Missing I/O semantics    │
│  └──────────────────────────────┘                              │
│       │                                                         │
│       ▼                                                         │
│  FactoryConfig (machines, jobs)                                │
│       │                                                         │
│       ├─────────────────────────────────┐                      │
│       │                                 │                      │
│       │  situation_text                 │                      │
│       │       │                         │                      │
│       ▼       │                         │                      │
│  ┌──────────────────────────────┐     │                       │
│  │  IntentAgent                 │     │  ✅ Tested extraction   │
│  │  text → ScenarioSpec         │     │  ❌ Missing correctness │
│  └──────────────────────────────┘     │                       │
│       │                               │                       │
│       ├───────────────────────────────┤                       │
│       │                               │                       │
│       ▼                               ▼                       │
│  ┌──────────────────────────────┐                              │
│  │  FuturesAgent                │  ✅ Tested generation       │
│  │  spec → [specs] (1-3)        │  ❌ Missing semantic check   │
│  └──────────────────────────────┘                              │
│       │                                                         │
│       ▼                                                         │
│  For each spec: simulate() → metrics                           │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────────────────────────┐                              │
│  │  BriefingAgent               │  ✅ Tested output format    │
│  │  metrics → markdown          │  ❌ Missing accuracy check   │
│  └──────────────────────────────┘                              │
│       │                                                         │
│       ▼                                                         │
│  User briefing (markdown)                                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## What's Tested ✅

| Component | What's Tested |
|-----------|---------------|
| **OnboardingAgent** | • Fallback on LLM error • Empty input • Large factories • Never raises |
| **IntentAgent** | • Returns BASELINE/RUSH_ARRIVES/M2_SLOWDOWN • Fallback on error • ID normalization |
| **FuturesAgent** | • Generates 1-3 scenarios • Truncation • Fallback |
| **BriefingAgent** | • Markdown output • Context parameters • Fallback |
| **Adversarial Harness** | • Structural invariants (12 test cases) • JSON reports • HTTP endpoints |

## What's Missing ❌

### 1. OnboardingAgent Input→Output Modeling
**Problem**: Tests don't verify parsing correctness
```
Example MISSING test:
  Given: "3 machines: M1 (Assembly), M2 (Drill), M3 (Packing). J1: M1→2h, M2→3h, M3→1h, due 10am"
  Expected: FactoryConfig with 3 machines, J1 with 3 steps, M1 duration 2, due_time 10
  Current: ✓ Test mocks LLM response, doesn't verify LLM actually parses this correctly
```

**Gap Severity**: 🔴 HIGH - Core parsing functionality not validated semantically

**Fix**: Add 15-20 tests that define expected FactoryConfig for each adversarial case

---

### 2. IntentAgent Scenario Identification
**Problem**: Tests verify scenario types are *handled*, not that they're *identified correctly*
```
Example MISSING test:
  Given: "J2 just arrived, must be first priority"
  Expected: ScenarioSpec with scenario_type=RUSH_ARRIVES, rush_job_id="J2"
  Current: ✓ Test has RUSH_ARRIVES case, but doesn't test that agent IDENTIFIES it from text
```

**Gap Severity**: 🔴 HIGH - Decision pipeline depends on correct scenario identification

**Fix**: Add 10 tests that verify scenario type identification from situation_text

---

### 3. FuturesAgent Scenario Diversity & Coherence
**Problem**: Tests verify generation happens, not that scenarios are meaningful
```
Example MISSING test:
  Given: BASELINE scenario for factory with 3 machines
  Expected: 2-3 alternative scenarios that are different and respect factory constraints
  Current: ✓ Test verifies 1-3 are returned, ✗ doesn't verify they're coherent or diverse
```

**Gap Severity**: 🟡 MEDIUM - User doesn't benefit if alternatives are nonsensical

**Fix**: Add 8 tests validating scenario coherence, diversity, constraint satisfaction

---

### 4. BriefingAgent Accuracy
**Problem**: Tests verify output is a string, not that it's *correct*
```
Example MISSING test:
  Given: ScenarioMetrics with makespan=10h, bottleneck_machine_id="M2", lateness={J1: 2h}
  Expected: Briefing mentions "10 hours", "M2", "J1 is 2 hours late"
  Current: ✓ Test verifies markdown is returned, ✗ doesn't verify content accuracy
```

**Gap Severity**: 🟡 MEDIUM - User sees inaccurate briefings

**Fix**: Add 12 tests validating briefing reflects metrics and constraints

---

### 5. Adversarial Harness: Expected Outputs
**Problem**: Harness generates reports for manual inspection, doesn't auto-validate semantics
```
Example MISSING:
  adversarial_cases.yaml lists 12 cases but doesn't specify expected FactoryConfig/ScenarioSpec
  run_adversarial.py validates structural invariants but not semantic correctness
  No automated failure on parsing mistakes
```

**Gap Severity**: 🟡 MEDIUM - Manual inspection doesn't scale, regressions not caught automatically

**Fix**: Add expected outputs to each case, implement semantic validation in harness

---

## Quick Stats

**Current Test Coverage**:
- OnboardingAgent: 10 tests (fallback, error handling) + 0 semantic tests
- IntentAgent: 7 tests (scenario handling) + 0 identification tests
- FuturesAgent: 5 tests (generation) + 0 coherence tests
- BriefingAgent: 5 tests (format) + 0 accuracy tests
- Adversarial: 12 cases + structural invariants only

**Needed Tests**:
- OnboardingAgent: +15-20 semantic tests
- IntentAgent: +10 identification tests
- FuturesAgent: +8 coherence tests
- BriefingAgent: +12 accuracy tests
- Adversarial: Expected outputs + semantic validation

**Total Missing**: ~45-65 tests to close gaps

---

## Recommended Priority Order

1. **🔴 Phase 1**: OnboardingAgent I/O tests (2-3 days)
   - Highest impact: Core parsing must work correctly
   - Blocks other agents: Depends on valid FactoryConfig

2. **🔴 Phase 2**: IntentAgent + FuturesAgent scenario tests (2-3 days)
   - High impact: Decision pipeline depends on scenario correctness
   - Enables briefing tests: Briefing needs correct scenarios to validate

3. **🟡 Phase 3**: BriefingAgent accuracy tests (2 days)
   - Medium impact: User-facing output quality
   - Depends on valid metrics from simulation

4. **🟡 Phase 4**: End-to-end pipeline tests (1 day)
   - Medium impact: Integration validation
   - Catches cross-agent bugs

5. **🟢 Phase 5**: Harness automation (2-3 days)
   - Lower priority: Enhances existing harness
   - Enables continuous validation

---

## Examples of What Tests Should Look Like

### Example 1: OnboardingAgent Semantic Test
```python
def test_parses_clean_canonical_correctly():
    """Verify clean_canonical factory description produces expected FactoryConfig."""
    factory_text = load_from_adversarial_corpus("clean_canonical")

    with patch("backend.agents.call_llm_json") as mock_llm:
        # Mock LLM with realistic response (from human or known-good trace)
        mock_llm.return_value = FactoryConfig(
            machines=[
                Machine(id="M1", name="Assembly workstation"),
                Machine(id="M2", name="Drill and mill station"),
                Machine(id="M3", name="Packaging station"),
            ],
            jobs=[
                Job(id="J1", steps=[
                    Step(machine_id="M1", duration_hours=2),
                    Step(machine_id="M2", duration_hours=3),
                    Step(machine_id="M3", duration_hours=1),
                ], due_time_hour=10),
                # ...J2, J3...
            ],
        )

        agent = OnboardingAgent()
        result = agent.run(factory_text)

        # Verify structure matches expected
        assert len(result.machines) == 3
        assert len(result.jobs) == 3
        assert result.machines[0].id == "M1"
        assert result.jobs[0].due_time_hour == 10
        assert len(result.jobs[0].steps) == 3
        assert result.jobs[0].steps[0].duration_hours == 2
```

### Example 2: IntentAgent Identification Test
```python
def test_identifies_rush_arrives_intent():
    """Verify IntentAgent correctly identifies RUSH_ARRIVES scenario."""
    situation = "J2 just arrived and must be completed first before anything else."
    factory = build_toy_factory()

    with patch("backend.agents.call_llm_json") as mock_llm:
        # Mock: LLM correctly identifies RUSH_ARRIVES with rush_job_id="J2"
        mock_llm.return_value = ScenarioSpec(
            scenario_type=ScenarioType.RUSH_ARRIVES,
            rush_job_id="J2",
        )

        agent = IntentAgent()
        spec, explanation = agent.run(situation, factory)

        # Verify correctness
        assert spec.scenario_type == ScenarioType.RUSH_ARRIVES
        assert spec.rush_job_id == "J2"
        assert "priority" in explanation.lower() or "first" in explanation.lower()
```

### Example 3: BriefingAgent Accuracy Test
```python
def test_briefing_reflects_bottleneck_machine():
    """Verify briefing mentions bottleneck machine from metrics."""
    metrics = ScenarioMetrics(
        makespan_hour=10.5,
        bottleneck_machine_id="M2",
        bottleneck_utilization=0.92,
        job_lateness={"J1": 0, "J2": 2.5},
    )

    with patch("backend.agents.call_llm_json") as mock_llm:
        mock_llm.return_value = "# Results\nBottleneck: M2 (92% utilized)...\nJ2 is 2.5 hours late."

        agent = BriefingAgent()
        briefing = agent.run(metrics)

        # Verify accuracy
        assert "M2" in briefing or "machine 2" in briefing.lower()
        assert "92" in briefing or "0.92" in briefing  # Utilization
        assert "2.5" in briefing or "2 hours" in briefing  # Lateness
```

---

## Benefits of Closing These Gaps

✅ **Catches parsing regressions** when LLM prompts change
✅ **Validates scenario identification** before full simulation
✅ **Ensures briefing accuracy** for user-facing output
✅ **Enables continuous validation** in CI/CD pipeline
✅ **Documents expected behavior** for all agents
✅ **Prevents subtle bugs** in cross-agent coordination

---

**Full detailed report**: See `AGENT_TESTING_REPORT.md`
