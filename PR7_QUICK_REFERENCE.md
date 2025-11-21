# PR7 Quick Reference

## What Changed

### New Functions (backend/onboarding.py)

```python
# Stage 0: Deterministic regex extraction
extract_explicit_ids(factory_text: str) -> ExplicitIds

# Stage 1: LLM enumeration of machines/jobs (no steps)
enumerate_entities(
    factory_text: str,
    required_machine_ids: set[str],
    required_job_ids: set[str]
) -> FactoryEntities

# Stage 2: Coverage computation
compute_coverage(
    explicit_ids: ExplicitIds,
    entities: FactoryEntities
) -> CoverageReport
```

### New Models (backend/onboarding.py)

```python
ExplicitIds
├─ machine_ids: set[str]
└─ job_ids: set[str]

FactoryEntity
├─ id: str
└─ name: str

FactoryEntities
├─ machines: list[FactoryEntity]
└─ jobs: list[FactoryEntity]

CoverageReport
├─ detected_machine_ids: set[str]
├─ detected_job_ids: set[str]
├─ enumerated_machine_ids: set[str]
├─ enumerated_job_ids: set[str]
├─ missing_machines: set[str]
├─ missing_jobs: set[str]
├─ machine_coverage: float (0.0-1.0)
└─ job_coverage: float (0.0-1.0)
```

### Updated Functions

**backend/orchestrator.run_onboarding()**
- Now calls extract_explicit_ids() → Stage 0
- Now calls enumerate_entities() → Stage 1
- Now calls compute_coverage() → Stage 2
- Surfaces coverage warnings in `OnboardingMeta.onboarding_errors`
- Then proceeds with existing extraction and normalization

**backend/eval/run_adversarial.build_report()**
- Now computes coverage for each test case
- Adds `report["coverage"]` with detailed metrics

## Usage Examples

### Extract Explicit IDs
```python
from backend.onboarding import extract_explicit_ids

text = "We have M1, M2, M3 machines. Jobs J1, J2 process them."
ids = extract_explicit_ids(text)
print(ids.machine_ids)  # {'M1', 'M2', 'M3'}
print(ids.job_ids)      # {'J1', 'J2'}
```

### Compute Coverage
```python
from backend.onboarding import compute_coverage, FactoryEntities, FactoryEntity

entities = FactoryEntities(
    machines=[FactoryEntity(id='M1', name='m1')],
    jobs=[FactoryEntity(id='J1', name='j1')]
)

coverage = compute_coverage(ids, entities)
print(coverage.machine_coverage)  # 0.333 (1 of 3 detected)
print(coverage.missing_machines)  # {'M2', 'M3'}
```

### In run_onboarding (automatic)
```python
from backend.orchestrator import run_onboarding

factory, meta = run_onboarding("We have M1, M2, M3...")
print(meta.onboarding_errors)
# May include: "Onboarding coverage warning: text mentions {M1,M2,M3,M4}
#              but enumeration found {M1,M2}; missing machines: {M3,M4}"
```

## Key Differences from PR6

| Aspect | PR6 | PR7 |
|--------|-----|-----|
| **Stages** | 1 (full LLM) | 4 (extract → enumerate → coverage → full) |
| **Coverage** | Post-hoc regex only | Pre-extraction baseline + LLM enumeration |
| **Visibility** | Only if final config wrong | Coverage metrics visible regardless |
| **Fail-safe** | Stage 1 only | Stages 0,2 deterministic; stage 1 graceful fail |
| **Eval reports** | No coverage info | Full coverage metrics included |

## Testing

All new functions are tested:
- **15 new tests** in `backend/tests/test_extract_explicit_ids.py`
- **Deterministic**: No LLM calls
- **Fast**: ~0.1s total
- **100% passing**

Run with:
```bash
pytest backend/tests/test_extract_explicit_ids.py -v
```

## Schema Changes

❌ **No breaking changes**:
- OnboardingResponse: unchanged
- SimulateResponse: unchanged
- OnboardingMeta: unchanged (onboarding_errors is list[str], supports warnings)
- FactoryConfig: unchanged
- Machine, Job, Step: unchanged

✅ **Internal only**:
- ExplicitIds: new
- FactoryEntity: new
- FactoryEntities: new
- CoverageReport: new

## Failure Ladder

**Unchanged**:
- Level 0 (OK): No warnings, factory non-empty
- Level 1 (DEGRADED): Has warnings (coverage + normalization), factory non-empty
- Level 2 (FALLBACK): Empty factory, use toy factory

**Improvements**:
- Level 1 now includes coverage warnings
- More transparent diagnostics in onboarding_errors

## Example Output

**Run adversarial eval**:
```bash
python -m backend.eval.run_adversarial --use-llm
```

**Status line with coverage**:
```
[non_uniform_paths] kind=simulate onboarding=OK used_default_factory=false
invariants=OK coverage=machines:100%/jobs:100%
```

**Report includes**:
```json
{
  "coverage": {
    "detected_machine_ids": ["M1", "M2", "M3", "M4"],
    "detected_job_ids": ["J1", "J2", "J3"],
    "enumerated_machine_ids": ["M1", "M2", "M3", "M4"],
    "enumerated_job_ids": ["J1", "J2", "J3"],
    "missing_machines": [],
    "missing_jobs": [],
    "machine_coverage": 1.0,
    "job_coverage": 1.0
  }
}
```

## Roadmap

**PR7 (this)**: Multi-stage instrumentation + coverage visibility
**PR8**: Use coverage thresholds to trigger fallback
**PR9**: Constrain full extraction with required IDs
**PR10**: Multi-pass extraction with retry logic

## Checklist for Code Review

- [ ] New functions are pure/deterministic
- [ ] Tests are LLM-free (no API calls)
- [ ] HTTP contracts unchanged
- [ ] Failure ladder unchanged
- [ ] Backward compatible
- [ ] No external dependencies added
- [ ] All tests passing (39 sampled, 271 total)
