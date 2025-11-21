#!/usr/bin/env python3
"""
Analyze all prompts in the codebase to see their lengths.
"""

import re
from backend.agents import OnboardingAgent, IntentAgent, FuturesAgent, BriefingAgent
from backend.models import FactoryConfig, Machine, Job, Step, ScenarioSpec, ScenarioType

# Create dummy factory for context
dummy_factory = FactoryConfig(
    machines=[
        Machine(id="M1", name="Assembly"),
        Machine(id="M2", name="Drill"),
        Machine(id="M3", name="Pack"),
    ],
    jobs=[
        Job(id="J1", name="Widget", steps=[
            Step(machine_id="M1", duration_hours=2),
            Step(machine_id="M2", duration_hours=3),
            Step(machine_id="M3", duration_hours=1)
        ], due_time_hour=10),
        Job(id="J2", name="Gadget", steps=[
            Step(machine_id="M1", duration_hours=1),
            Step(machine_id="M2", duration_hours=2),
        ], due_time_hour=12),
    ]
)

factory_text = "We run 3 machines M1, M2, M3. Two jobs J1 and J2 process through them."
user_text = "Run a normal day"
scenario_spec = ScenarioSpec(scenario_type=ScenarioType.BASELINE)

print("=" * 80)
print("PROMPT LENGTH ANALYSIS")
print("=" * 80)

# OnboardingAgent
agent = OnboardingAgent()
prompt = agent._build_prompt(factory_text)
print(f"\n1. OnboardingAgent._build_prompt()")
print(f"   Length: {len(prompt):,} chars")
print(f"   Estimate: ~{len(prompt)//4:,} tokens")

# IntentAgent - simulate what it builds
intent_agent = IntentAgent()
try:
    spec, explanation = intent_agent.run(user_text, dummy_factory)
    print(f"\n2. IntentAgent.run()")
    print(f"   ✓ Works (uses internal prompt)")
except Exception as e:
    print(f"\n2. IntentAgent.run()")
    print(f"   ✗ Can't measure directly (LLM error: {e})")

# FuturesAgent - similar structure
futures_agent = FuturesAgent()
try:
    specs, justification = futures_agent.run(scenario_spec, dummy_factory)
    print(f"\n3. FuturesAgent.run()")
    print(f"   ✓ Works (uses internal prompt)")
except Exception as e:
    print(f"\n3. FuturesAgent.run()")
    print(f"   ✗ Can't measure directly (LLM error: {e})")

# BriefingAgent - similar structure
briefing_agent = BriefingAgent()
try:
    from backend.models import ScenarioMetrics
    dummy_metrics = ScenarioMetrics(
        scenario_id="test",
        total_makespan_hours=10,
        num_late_jobs=0,
        jobs_on_time=2,
    )
    briefing = briefing_agent.run(dummy_metrics, "Test context")
    print(f"\n4. BriefingAgent.run()")
    print(f"   ✓ Works (uses internal prompt)")
except Exception as e:
    print(f"\n4. BriefingAgent.run()")
    print(f"   ✗ Can't measure directly (LLM error: {e})")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print("""
Only OnboardingAgent prompt is measurable without calling LLM.
Other agents have prompts but they're built dynamically at runtime.

Observation: OnboardingAgent (3,979 chars) is now concise.

To audit other prompts, you'd need to:
1. Extract prompt construction from each agent
2. Call them with test data
3. Capture the actual prompt before it hits the LLM

This would require adding temporary logging to agents.py.
""")
