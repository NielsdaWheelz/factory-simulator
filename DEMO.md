# Factory Day Simulator: v0.1 Prototype

## Overview

Multi-agent LLM orchestration system for manufacturing decision support. Accepts free-form factory descriptions, parses them through five validation stages, generates 1–3 scenario variations, simulates each with a deterministic EDD scheduler, and produces an operational briefing with risk assessment. **Built in 2 days by one engineer. Full pipeline observability via debug UI.**

## What This Demo Shows

- **Multi-stage onboarding (O0–O4)**: Factory parsing with explicit coverage validation; 100% ID coverage enforced or fallback to safe default
- **Multi-stage decision pipeline (D1–D5)**: User intent → scenario expansion → deterministic simulation → metrics → briefing
- **Strict LLM validation**: All agent outputs validated against Pydantic schemas; agents reference only real entities from factory config
- **Deterministic simulation core**: Identical factory + scenario spec → identical scheduled output, every time (EDD scheduler, zero randomness)
- **Orchestration of four LLM agents**: Intent classifier, futures expander, briefing synthesizer, with graceful fallback on error
- **Full pipeline-level observability**: Accordion debug UI exposes all 10 stages (status, summary data, errors) for root-cause analysis

## 20-Second Demo Script

```
1. Enter factory: "3 machines (M1, M2, M3), 3 jobs (J1, J2, J3) with routing."
2. Situation: "Rush order for J2, must complete by hour 10."
3. Click Simulate.
4. [Wait 2–3 seconds for pipeline.]
5. View briefing: metrics table shows makespan, bottleneck (M2 at 95%), J3 lateness (2h).
6. Open debug accordion.
7. Click [D1]: Intent = RUSH_ARRIVES (J2).
8. Click [D4]: Three scenarios compared (BASELINE, RUSH, AGGRESSIVE).
9. Click [O4]: Coverage = 100% (all machines and jobs enumerated).
10. Verify status badge: "SUCCESS" (all 10 stages passed).
```

## How This Maps to ProDex's Job Description

- **Multi-agent LLM workflows for production reliability**: 10-stage pipeline with 4 distinct agents; per-agent error handling with safe fallbacks (no unhandled exceptions)
- **Validate and normalize unstructured inputs**: O0–O4 staged extraction with dual-layer validation (schema + explicit ID coverage) and deterministic repair
- **Ensure determinism and auditability**: EDD scheduler produces reproducible schedules; all 10 pipeline stages recorded in debug payload for post-hoc review
- **Implement comprehensive error handling**: Onboarding coverage < 100% → toy factory fallback; LLM timeouts → deterministic templates (system always completes)
- **Handle edge cases and coverage validation**: Regex extraction (O0) anchors ground truth; O4 verifies 100% coverage or triggers fallback; no silent data loss
- **Demonstrate strong systems thinking**: Staged extraction beats monolithic parsing; clear stage separation; explicit data flow; observable at every boundary

## Deep Dive

Full technical breakdown (architecture, stage-by-stage walkthrough, testing strategy, failure modes) is in [DEMO_CHECKLIST.md](DEMO_CHECKLIST.md).
