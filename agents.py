"""
Agentic Interpretation Layer

This module will define the three LLM agents that form the agentic boundaries:

1. IntentAgent: Parses free-form planner text -> ScenarioIntent
   - Input: user text + factory summary
   - Output: structured intent (objective, protected_job_id, risk_tolerance)
   - Constraints: objective and risk_tolerance from fixed enums, protected_job_id must reference real job

2. FuturesAgent: Converts ScenarioIntent -> list of ScenarioSpec
   - Input: factory summary + intent
   - Output: 2-3 concrete scenarios (BASELINE, RUSH_ARRIVES, M2_SLOWDOWN)
   - Constraints: closed set of scenario types, all refs must be to existing jobs/machines

3. BriefingAgent: Translates metrics -> markdown morning briefing
   - Input: factory summary, scenarios, metrics, intent
   - Output: structured markdown briefing with fixed sections
   - Constraints: all job/machine IDs must be real, metrics must be cited correctly

For now: no models, no prompts, no LLM logic, placeholder only.
"""
