"""
Orchestration & Pipeline Module

This module will define the main orchestration pipeline:

run_pipeline(user_text: str) -> FactoryState

Orchestrates the complete flow:
1. Initialize FactoryConfig and FactoryState
2. Intent Agent: parse user text -> ScenarioIntent
3. Futures Agent: generate scenarios -> list[ScenarioSpec]
4. Simulation: run each scenario -> SimulationResult[]
5. Metrics: compute metrics from results -> ScenarioMetrics[]
6. Briefing Agent: generate markdown briefing
7. Finalize: populate FactoryState, return

Validation happens explicitly at each contract boundary between agents and simulation.
State is passed explicitly through the pipeline, never mutated implicitly.

For now: no code beyond this docstring, placeholder only.
"""
