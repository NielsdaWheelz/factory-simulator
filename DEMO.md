# DEMO SCRIPT: Data Flow Walkthrough

## Corrections to Your Script

1. **Accurate**: "post to server calls `run_agent()` in `agent_engine`" ✓
2. **Accurate**: TypedDict vs Pydantic - yes, LangGraph uses TypedDict, you use Pydantic
3. **Minor correction**: `generate_plan()` is called `_generate_plan()` (internal function, not callable by LLM)
4. **Accurate**: Plan steps are validated to `PlanStepType` enum
5. **Accurate**: Tools call onboarding functions which call `call_llm_json()`
6. **Missing detail**: The onboarding pipeline is 5 sub-stages (O0-O4), not one LLM call

---

## The Data Flow Walkthrough (Follow the Data)

### PHASE 0: HTTP Entry
```
User Browser
    │
    ▼
POST /api/agent  [server.py:214]
    │ {user_request, max_steps, llm_budget}
    ▼
agent_endpoint(req: AgentRequest)  [server.py:215]
    │
    ▼
```
- **LangGraph equivalent**: None. This is your HTTP adapter layer.
- **Data in**: `AgentRequest` (user_request: str, max_steps: int, llm_budget: int)
- **Data out**: Calls `run_agent()`

---

### PHASE 1: State Initialization (LangGraph: "StateGraph.compile()")
```
run_agent(user_request, max_steps, llm_budget)  [agent_engine.py:544]
    │
    ▼
state = AgentState(...)  [agent_engine.py:559]
    │ user_request, max_steps, llm_call_budget
    │ status=RUNNING, steps=0, plan=[]
    ▼
registry = create_default_registry()  [agent_tools.py:1839]
    │ registers: parse_factory, simulate_scenario, generate_briefing, etc.
    ▼
```
- **LangGraph equivalent**: `StateGraph` definition + `.compile()`
- **Your implementation**: `AgentState` Pydantic model
- **Key file**: `agent_types.py:311-494` - the full state schema

---

### PHASE 2: Planning (LangGraph: "Conditional Edges" / Router)
```
_generate_plan(state, registry)  [agent_engine.py:118]
    │
    ├─► _build_planning_observation(state)  [agent_engine.py:93]
    │       │ Builds prompt: user_request + capabilities + constraints
    │       ▼
    │
    ├─► call_llm_json_with_metadata(prompt, PlanResponse)  [llm.py:35]
    │       │ OpenAI API call (JSON mode)
    │       │ Schema: PlanResponse {plan: list[dict], reasoning: str}
    │       ▼
    │
    └─► Validate each step.type against PlanStepType enum  [agent_engine.py:204]
            │ Converts to list[PlanStep]
            │ Stores in state.plan
            ▼
```
- **LangGraph equivalent**: Conditional edges / routing function
- **Your implementation**: LLM generates plan → validated to enum → stored in state
- **Key difference**: LangGraph uses function annotations or `should_continue()` conditionals; you use LLM-generated plan array

**Data flow**:
- **In**: `state.user_request`, `state.factory_text`
- **LLM call**: `PlanResponse` schema
- **Out**: `state.plan = [PlanStep(type=ensure_factory), PlanStep(type=simulate_baseline), ...]`

---

### PHASE 3: Execution Loop (LangGraph: "RunLoop" / Pregel)
```
while state.is_running():  [agent_engine.py:575]
    │
    ├─► step = state.get_next_pending_step()  [agent_types.py:685]
    │       │ Finds first step with status="pending"
    │       ▼
    │
    ├─► state.mark_plan_step_running(step.id)  [agent_types.py:662]
    │       │ Sets step.status = "running"
    │       ▼
    │
    ├─► _execute_plan_step(state, step, registry)  [agent_engine.py:447]
    │       │ Routes to executor based on step.type
    │       ▼
    │
    ├─► state.mark_plan_step_done(step.id)  [agent_types.py:670]
    │       │ Sets step.status = "done"
    │       ▼
    │
    └─► state.increment_step()  [agent_types.py:511]
            │ steps += 1, check max_steps
            ▼
```
- **LangGraph equivalent**: `app.invoke()` → Pregel message-passing loop
- **Your implementation**: Simple `while` loop with step counter and budget checks
- **Key invariants**: `llm_budget`, `max_steps`, `consecutive_errors`

---

### PHASE 4: Node Dispatch (LangGraph: "Nodes")
```
_execute_plan_step(state, step, registry)  [agent_engine.py:447]
    │
    │   executors = {
    │       PlanStepType.ENSURE_FACTORY: _execute_ensure_factory,
    │       PlanStepType.SIMULATE_BASELINE: _execute_simulate_baseline,
    │       PlanStepType.SIMULATE_RUSH: _execute_simulate_rush,
    │       PlanStepType.SIMULATE_SLOWDOWN: _execute_simulate_slowdown,
    │       PlanStepType.GENERATE_BRIEFING: _execute_generate_briefing,
    │       PlanStepType.DIAGNOSTIC: _execute_diagnostic,
    │   }
    │
    └─► executors[step.type](state, step, registry)
```
- **LangGraph equivalent**: Node definitions via `@graph.node` decorator
- **Your implementation**: Dictionary dispatch based on `PlanStepType` enum
- **Key insight**: Each executor is a pure function: `(state, step, registry) → Optional[ErrorInfo]`

---

### PHASE 5: Tool Execution - ParseFactoryTool (The Complex One)
```
_execute_ensure_factory(state, step, registry)  [agent_engine.py:276]
    │
    ├─► tool = registry.get("parse_factory")  [agent_engine.py:287]
    │
    └─► tool.execute({"description": state.factory_text}, state)  [agent_tools.py:201]
            │
            │ ╔══════════════════════════════════════════════════════════╗
            │ ║  ONBOARDING SUB-PIPELINE (5 Stages)                      ║
            │ ╚══════════════════════════════════════════════════════════╝
            │
            ├─► O0: extract_explicit_ids(factory_text)  [onboarding.py:139]
            │       │ REGEX-ONLY, no LLM
            │       │ Returns: ExplicitIds {machine_ids: set, job_ids: set}
            │       ▼
            │
            ├─► O1: run_multi_pass_onboarding(factory_text, num_passes=2)  [onboarding.py:1508]
            │       │ Runs 2 extraction passes with different modes
            │       │
            │       ├─► run_onboarding_pass(factory_text, "default")  [onboarding.py:1445]
            │       │       │
            │       │       ├─► extract_coarse_structure(text, ids)  [onboarding.py:217]
            │       │       │       │ LLM CALL #1: CoarseStructure schema
            │       │       │       │ Returns: {machines: [{id, name}], jobs: [{id, name}]}
            │       │       │       ▼
            │       │       │
            │       │       ├─► extract_steps(text, coarse)  [onboarding.py:328]
            │       │       │       │ LLM CALL #2: RawFactoryConfig schema
            │       │       │       │ Returns: machines + jobs with steps/durations/due_times
            │       │       │       ▼
            │       │       │
            │       │       └─► validate_and_normalize_with_diagnostics(raw)  [onboarding.py:1085]
            │       │               │ NO LLM - Pure validation
            │       │               │ Enforces invariants, normalizes durations
            │       │               │ Returns: NormalizationResult {factory, warnings}
            │       │               ▼
            │       │
            │       └─► run_onboarding_pass(factory_text, "conservative")
            │               │ (Same 3 steps, different prompt phrasing)
            │               ▼
            │
            ├─► O2: (inline) validate_and_normalize  [onboarding.py:936]
            │       │ Already done in multi-pass, but exposed for data flow viz
            │       ▼
            │
            ├─► O3: assess_coverage(ids, factory)  [onboarding.py:532]
            │       │ NO LLM - Pure comparison
            │       │ Compares regex-extracted IDs to LLM-parsed factory
            │       │ Returns: CoverageReport {machine_coverage, job_coverage, missing_*}
            │       ▼
            │
            ├─► O4: compute_factory_diff(primary, alt)  [onboarding.py:1315]
            │       │ NO LLM - Pure structural diff
            │       │ Compares two FactoryConfigs
            │       │ Returns: FactoryDiff {machines_added, jobs_removed, routing_differences, ...}
            │       ▼
            │
            └─► compute_onboarding_score(coverage_issues, repairs, conflicts)  [onboarding.py:1214]
                    │ Returns: (score: int, trust: str)
                    │ Updates: state.onboarding_score, state.onboarding_trust
                    ▼
```

**Data persisted to state**:
- `state.factory` = validated FactoryConfig
- `state.onboarding_issues` = list of issues
- `state.alt_factories` = alternative interpretations
- `state.clarifying_questions` = generated questions

---

### PHASE 6: SimulateScenarioTool
```
_execute_simulate_baseline(state, step, registry)  [agent_engine.py:308]
    │
    └─► tool.execute({"scenario_type": "baseline"}, state)  [agent_tools.py:853]
            │
            ├─► simulate(state.factory, spec)  [sim.py:167]
            │       │ apply_scenario(factory, spec)  → modified FactoryConfig
            │       │ simulate_baseline(modified_factory)  → SimulationResult
            │       ▼
            │
            └─► compute_metrics(factory, result)  [metrics.py]
                    │ Returns: ScenarioMetrics
                    │ {makespan_hour, job_lateness, bottleneck_machine_id, bottleneck_utilization}
                    ▼
```

**Data persisted to state**:
- `state.scenarios_run.append(spec)`
- `state.metrics_collected.append(metrics)`

---

### PHASE 7: GenerateBriefingTool
```
_execute_generate_briefing(state, step, registry)  [agent_engine.py:396]
    │
    └─► tool.execute({include_recommendations: True}, state)  [agent_tools.py:1186]
            │
            └─► BriefingAgent().run(metrics, context, onboarding_context, ...)  [agents.py:1080]
                    │
                    └─► call_llm_json(prompt, BriefingResponse)  [llm.py:90]
                            │ LLM CALL: BriefingResponse {markdown: str}
                            ▼
```

**Data persisted to state**:
- `state.complete(briefing)` → sets `state.final_answer`, `state.status = DONE`

---

### PHASE 8: Response Serialization
```
agent_endpoint(req)  [server.py:215]
    │
    ├─► _build_trace_from_state(state)  [server.py:398]
    │
    └─► AgentResponse.model_dump()  [server.py:364]
            │ Serializes to JSON for frontend
            ▼
```

---

## LangGraph Mapping Table

| **LangGraph Concept** | **Your Implementation** | **File:Line** |
|:---|:---|:---|
| `StateGraph(State)` | `AgentState(BaseModel)` | `agent_types.py:311` |
| State channels | Pydantic fields (factory, metrics_collected, plan, etc.) | `agent_types.py:381-497` |
| `graph.add_node("name", func)` | `executors = {PlanStepType.X: _execute_X}` | `agent_engine.py:449` |
| `graph.add_edge("a", "b")` | `state.plan` list (sequential) | `agent_engine.py:570` |
| Conditional edges | `_generate_plan()` + `PlanStepType` enum | `agent_engine.py:118` |
| `graph.compile()` | `create_default_registry()` | `agent_tools.py:1839` |
| `app.invoke(input)` | `run_agent(user_request)` | `agent_engine.py:544` |
| Checkpointing | `state.plan[i].status` tracking | `agent_types.py:119` |
| Tool interface | `Tool` ABC + `ToolRegistry` | `agent_tools.py:57,1805` |
| `ToolNode` | `_execute_*` functions calling `registry.get(name).execute()` | `agent_engine.py:276-410` |

---

## The Pitch (Bullet Points for Interview)

### "I built my own LangGraph"

- **State Schema**: `AgentState` in `agent_types.py`
  - LangGraph uses `TypedDict`; I use Pydantic
  - Pydantic gives me runtime validation, `.model_dump()` for JSON, field-level defaults
  - 190 lines of state definition with full type safety

- **Nodes**: Python functions in `agent_engine.py`
  - `_execute_ensure_factory`, `_execute_simulate_baseline`, etc.
  - Each node: `(state, step, registry) → Optional[ErrorInfo]`
  - Pure functions - no side effects except state mutation

- **Edges**: Dynamic plan array
  - LangGraph: explicit `add_edge()` calls or conditional functions
  - Me: LLM generates `list[PlanStep]` at step 0
  - Plan is validated against `PlanStepType` enum - no hallucinated step types
  - Edges are implicit: next pending step in array

- **Runtime**: `while state.is_running()` loop
  - LangGraph: Pregel message-passing
  - Me: Simple while loop with explicit budget/step checks
  - Budget enforcement: `state.increment_llm_calls()` returns False if exceeded
  - Error boundaries: try/except inside loop, typed `ErrorInfo`

- **Tools**: `Tool` ABC + `ToolRegistry`
  - `to_openai_schema()` generates function calling JSON
  - `execute()` returns `ToolResult` with success/error
  - Registry pattern: `registry.get("parse_factory").execute(args, state)`

### Why roll my own?

- **Control**: I own the error taxonomy (`ErrorType` enum)
- **Type safety**: Pydantic validates every LLM output
- **Observability**: `state.data_flow`, `state.llm_calls` - first-class tracing
- **Domain fit**: Industrial simulations need hard invariants, not "close enough"
- **Demo-ability**: I can point to every line of code, explain every decision